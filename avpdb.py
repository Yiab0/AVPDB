#!/usr/local/bin/env python3

# Author: Yiab
# Copyright: This module is licensed under GPL v3.0.

"""
A Discord bot for the AVPSO guild. Tracks quotes and show schedule, as well as serves other miscellaneous functions.
"""

import os
import os.path
import sqlite3
import datetime
import sys
import subprocess
import re
import json
import urllib
import random
import configparser
import pickle
import itertools
import threading
import asyncio
import calendar
import rrulemap
import durationparse
from copy import deepcopy
from typing import Optional, Union, Callable, Any
from collections.abc import Iterable

if os.path.isdir("avpdb"):
	os.chdir("avpdb")

_config_filename = "config.ini"
_cfg = configparser.ConfigParser()
_cfg.read(_config_filename)
_params = _cfg["AVPDB"]
_cfg_lock = threading.RLock()

subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt', '--upgrade'])
#subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--upgrade', 'discord.py', 'xdice', 'python-dateutil'])

import dateutil.parser, dateutil.rrule, dateutil.tz
import discord
from discord.ext import commands, tasks
from xdice import roll

_token = _params.get("DiscordToken")
_guildname = _params.get("Guild").lower()
_main_guild = None
_pantheon = None

_cpx = _params.get("CommandPrefix")
_max_quote_display = int(_params.get("QuoteDisplayCap"))
_brandon_url = _params.get("BrandonImageURL")
_painscale_url = _params.get('PainScaleURL')
_timestamp_zoned = "[%Y-%m-%d %H:%M:%S {tz}]"
_timestamp_unzoned = '[%Y-%m-%d %H:%M:%S]'
_timezone_url = _params.get('TimezoneURL')
_brandon_frequency_cap = datetime.timedelta(minutes=int(_params.get('BrandonFrequency')))
_last_brandon = datetime.datetime.now(dateutil.tz.UTC) - 2*_brandon_frequency_cap
_random_dog_url = "https://api.thedogapi.com/v1/images/search"
_backup_random_dog_url = "https://dog.ceo/api/breeds/image/random"
_random_cat_url = "https://api.thecatapi.com/v1/images/search"
_botsource_url = 'https://github.com/Yiab0/AVPDB'
_last_connect = datetime.datetime.now(dateutil.tz.UTC)
_total_uptime = pickle.loads(bytes.fromhex(_params.get('TotalUptime')))
_goosecifix_url = _params.get("GoosecifixURL")
_showtypes = json.loads(_params['ShowTypes'])
_reaction_patterns = { "Blobbyrape": None, "HONK": None, "Kay": None, "lee": None, "God": None, "spicybeef": None, 'Hesquatch': None, 'Goveganmotherfuckers': None, 'Tim_Noah': None, 'Oogene': None, 'interviewplant': None, 'Bombadil': None }
_fruit_emoji = [ '\N{Green Apple}', '\N{Red Apple}', '\N{Pear}', '\N{Tangerine}', '\N{Lemon}', '\N{Banana}', '\N{Watermelon}', '\N{Grapes}', '\N{Blueberries}', '\N{Strawberry}', '\N{Melon}', '\N{Cherries}', '\N{Peach}', '\N{Mango}', '\N{Pineapple}', '\N{Kiwifruit}', '\N{Tomato}', '\N{Coconut}', '\N{Chicken}', '\N{Avocado}', '\N{Olive}' ]
_autosave_timer = int(_params.get("AutosaveConfigTimer"))
_active_links = '\n'.join(map(lambda x: f'{x[0]}: {x[1]}', json.loads(_params['active links'])))
_inactive_links = '\n'.join(map(lambda x: f'{x[0]}: {x[1]}', json.loads(_params['inactive links'])))
_schedule = pickle.loads(bytes.fromhex(_params.get('Schedule')))
_album_folder = 'albumcovers'
_rpg_status = json.loads(_params.get('RPGStatus','{}'))

_intents = discord.Intents.default()
_intents.members = True
bot = commands.Bot(command_prefix=_cpx, description=f"A Discord bot for AVPSO. Type {_cpx}help for a list of commands.", intents=_intents, case_insensitive=True)

def _save_config() -> None:
	"""
	Save the current configuration to the default file.
	"""
	with _cfg_lock:
		_params['TotalUptime'] = pickle.dumps(_total_uptime + (datetime.datetime.now(dateutil.tz.UTC) - _last_connect)).hex()
		_params['RPGStatus'] = json.dumps(_rpg_status)
		with open(_config_filename, "w") as configfile:
			_cfg.write(configfile)
			print(f"{_dt_tostr()} Saved configuration.")

def _tz_fromstr(n: str) -> Union[dateutil.tz.tzutc, dateutil.tz.tzfile, None]:
	"""
	Translates the given `str` into a time zone.
	
	Parameters:
	
	- `n`: The string to interpret as a time zone.
	"""
	if n.upper() == 'UTC':
		return dateutil.tz.UTC
	return dateutil.tz.gettz(n)

def _dt_tostr(dt: Optional[datetime.datetime] = None) -> str:
	"""
	Represents a `datetime` as a `str` using the default timestamp for this program, together with canonical time zone.
	
	Parameters:
	
	- `dt` (default: now): The datetime to stringify.
	"""
	if dt == None:
		dt = datetime.datetime.now(dateutil.tz.UTC)
	return dt.strftime(_timestamp_zoned).format(tz = rrulemap._tz_tostr(dt.tzinfo))

db = sqlite3.connect("quotes.db")
cursor = db.cursor()
cursor.execute("CREATE TABLE IF NOT EXISTS quotes(hash INTEGER,user TEXT,message TEXT,date_added TEXT)")
cursor.execute("CREATE TABLE IF NOT EXISTS aliases(alias TEXT PRIMARY KEY,user TEXT)")
cursor.execute("CREATE TABLE IF NOT EXISTS honcs(latin TEXT, english TEXT, author TEXT)")
cursor.execute("CREATE TABLE IF NOT EXISTS schedule(datetime TEXT, description TEXT)")
cursor.execute("CREATE TABLE IF NOT EXISTS smells(name TEXT UNIQUE)")
cursor.execute("CREATE TABLE IF NOT EXISTS perversions(name TEXT UNIQUE, description TEXT)")
cursor.execute('CREATE TABLE IF NOT EXISTS users(name TEXT PRIMARY KEY, timezone TEXT)')
cursor.execute('CREATE TABLE IF NOT EXISTS albums(tweetid INTEGER PRIMARY KEY, band TEXT, album TEXT)')
cursor.execute('CREATE TABLE IF NOT EXISTS rapescenes(datetime TEXT)')
print(f"{_dt_tostr()} Loaded quote database.")

db.commit()

os.makedirs(_album_folder, exist_ok = True)

def _is_guild_owner() -> Callable[[discord.ext.commands.Context], bool]:
	"""
	Returns a predicate which determines whether or not the user who triggered an event is the guild owner.
	"""
	def predicate(ctx: discord.ext.commands.Context) -> bool:
		"""
		Determines whether or not the user who triggered an event is the guild owner.
		
		Parameters:
		
		- `ctx`: The invokation context.
		"""
		return ctx.guild is not None and ctx.guild.owner_id == ctx.author.id
	return commands.check(predicate)

def format_quote(quote: tuple[int, str, str, str]) -> discord.Embed:
	"""
	Formats a single stored quote as an embed.
	
	Parameters:
	
	- `quote`: From the quotes database; quote number, author, quote, datetime added
	"""
	embed = discord.Embed(title=f"Quote #{quote[0]}", description=f"\"{quote[2]}\"")
	embed.set_footer(text=f"{quote[3]}")
	user = find_user(quote[1])
	if user == None:
		embed.set_author(name=f"{quote[1]} *")
	else:
		embed.set_author(name=user.display_name)
	return embed

def insert_quote(user: Union[discord.Member, discord.User], message: str) -> tuple[bool, int]:
	"""
	Tries to insert a quote into the database. If the quote already exists from the same user, returns `False` and the quote number. If the quote doesn't already exist from the same user, inserts the quote and returns `True` and the quote number.
	
	Parameters:
	
	- `user`: The author of the quote.
	- `message`: The quote.
	"""
	h = hash(str(user) + message)
	cursor.execute("SELECT ROWID, user, message FROM quotes WHERE hash=?", (str(h),))
	for q in cursor.fetchall():
		if q[1] == str(user) and q[2] == message:
			return (False, q[0])
	cursor.execute("INSERT INTO quotes VALUES(?,?,?,?)", (str(h), str(user), message, _dt_tostr()))
	db.commit()
	return (True, cursor.lastrowid)

def get_id_from_string(x: str) -> Optional[int]:
	"""
	Tries to extract a Discord user id from the given string.
	
	Parameters:
	
	- `x`: A string that might represent a user id.
	"""
	if not isinstance(x,str):
		return None
	r = re.fullmatch("<@!?(\\d+)>", x)
	if r:
		return int(r.group(1))
	return None

def mention_or_str(user: Any) -> str:
	"""
	If the given entity has a mention, return that otherwise just turn the input into a string.
	
	Parameters:
	
	- `user`: The thing we want to mention.
	"""
	return getattr(user, 'mention', str(user))

def find_user(name: str) -> Optional[discord.Member]:
	"""
	Transforms a string into the user that string represents. Takes into account the bot's alias database and can retrieve users from the guild's names as well as the user id. Returns `None` if no such user can be found.
	
	Parameters:
	
	- `name`: The name of the user to be found.
	"""
	user = _main_guild.get_member_named(name)
	if user != None:
		return user
	q = get_id_from_string(name)
	if q != None:
		user = _main_guild.get_member(q)
		if user != None:
			return user
	q = cursor.execute("SELECT user FROM aliases WHERE alias=? LIMIT 1", (name.lower(),)).fetchone()
	if q != None:
		user = _main_guild.get_member_named(q[0])
		if user != None:
			return user
	return None

def to_user(name: str) -> str:
	"""
	Identical to `find_user` except that it returns the input if no such user can be found.
	
	Parameters:
	
	- `name`: The name of the user to be found.
	"""
	res = find_user(name)
	if res == None:
		return name
	return res

@bot.check
async def in_avpso(ctx: discord.ext.commands.Context) -> bool:
	"""
	Determines whether or not the given context is within the correct guild.
	"""
	if ctx.guild != None:
		return ctx.guild.name.lower() == _guildname
	return True

@bot.event
async def on_ready() -> None:
	"""
	Picks out the main guild, the pantheon, and all the needed custom emoji.
	"""
	global _last_connect, _main_guild, _pantheon
	print(f"{_dt_tostr()} Connected to Discord.")
	for g in bot.guilds:
		if g.name.lower() == _guildname:
			_main_guild = g
	if _main_guild == None:
		print(f"{_dt_tostr()} Unable to find the correct guild.")
	else:
		for r in _main_guild.roles:
			if r.name.lower() == 'the pantheon':
				_pantheon = r
				break
	for e in bot.emojis:
		if e.name in _reaction_patterns:
			_reaction_patterns[e.name] = e

@bot.command(aliases = [ 'log_rape' ], help = 'Logs that a rape scene was seen.')
async def logrape(ctx):
	global _timestamp_unzoned
	cursor.execute('INSERT INTO rapescenes VALUES(?)',(datetime.datetime.utcnow().strftime(_timestamp_unzoned),))
	await ctx.reply('Logged.')
	db.commit()

@bot.command(aliases = [ 'rape_check', 'check_rape', 'checkrape' ], help = 'How long since the last rape scene?')
async def rapecheck(ctx):
	global _timestamp_unzoned
	q = cursor.execute('SELECT datetime FROM rapescenes ORDER BY datetime DESC LIMIT 1').fetchone()[0]
	p = datetime.datetime.strptime(q, _timestamp_unzoned)
	c = datetime.datetime.utcnow()
	await ctx.reply(f'It has been {(c-p).days} days since the last rape scene on AVPSO.')

@bot.command(aliases = [ 'rapeless_record' ], help = 'The longest amount of time we have gone between rape scenes so far.')
async def rapelessrecord(ctx):
	global _timestamp_unzoned
	q = cursor.execute('SELECT datetime FROM rapescenes ORDER BY datetime').fetchall()
	p = list(map(lambda x: datetime.datetime.strptime(x[0], _timestamp_unzoned), q))
	d = 0
	for i in range(len(p)-1):
		d = max(d, (p[i+1]-p[i]).days)
	await ctx.reply(f'The longest time between rape scenes so far is {max(d, (datetime.datetime.utcnow()-p[-1]).days)} days.')

@bot.command(aliases=['add_alias'], brief="Adds an alias for a user.", help="Adds an alias for a user. The alias must be alphamuneric and begin with a letter. Aliases are not case sensitive.")
async def addalias(ctx, alias, username):
	if len(alias) == 0 or (not alias.isalnum()) or (not alias[0].isalpha()):
		await ctx.reply("You can only associate aliases which are alphanumeric and begin with a letter.")
		return
	q = cursor.execute("SELECT * FROM aliases WHERE alias=? LIMIT 1", (alias.lower(),)).fetchone()
	if q != None:
		await ctx.reply(f"{q[0]} is already an alias for {q[1]}.")
		return
	user = find_user(username)
	if user == None:
		await ctx.reply(f"Cannot find a user named {username}.")
		return
	cursor.execute("INSERT INTO aliases VALUES(?,?)", (alias.lower(), str(user)))
	cursor.execute("UPDATE quotes SET user=? WHERE LOWER(user)=?", (str(user), alias.lower()))
	await ctx.reply(f"Successfully added {alias} as an alias for {mention_or_str(user)}.")
	if cursor.rowcount > 0:
		await ctx.reply(f"Reattributed {str(cursor.rowcount)} old quote{'' if cursor.rowcount == 1 else 's'} to {mention_or_str(user)}.")
	db.commit()

@bot.command(aliases=['get_alias'], brief="What aliases a user has.", help="Retrieves aliases associated with the given username or alias.")
async def getalias(ctx, name):
	user = to_user(name)
	aliases = cursor.execute("SELECT alias FROM aliases WHERE user=?", (str(user),)).fetchall()
	if len(aliases) == 0:
		await ctx.reply(f"There are no aliases in the database for {mention_or_str(user)}.")
		return
	await ctx.reply(embed=discord.Embed(title=f"Aliases of {getattr(user,'display_name',str(user))}", description=", ".join([ q[0] for q in aliases ] + [ mention_or_str(user) ])))

@bot.command(aliases=['del_alias'], brief="Deletes an alias (restricted).", help="Deletes an alias from the database (only available to authorized users).")
@commands.is_owner()
async def delalias(ctx, name):
	cursor.execute("DELETE FROM aliases WHERE alias=?", (name.lower(),))
	if cursor.rowcount == 1:
		await ctx.reply(f"Deleted the alias {name.lower()}")
	elif cursor.rowcount == 0:
		await ctx.reply(f"There is no alias in the database for {name.lower()}.")
	else:
		await ctx.reply(f"Deleted (somehow) {str(cursor.rowcount)} aliase{'' if cursor.rowcount == 1 else 's'} for {name.lower()}.")

@bot.command(brief='Reattributes all quotes correctly (restricted).', help='Reattributes all quotes in the database to the appropriate usernames based on the current alias table (only available to authorized users).', hidden=True)
@commands.is_owner()
async def reattribute(ctx):
	all_quoted = map(lambda x: x[0], cursor.execute('SELECT DISTINCT user FROM quotes').fetchall())
	for n in all_quoted:
		n3 = to_user(n)
		nn = str(n3)
		if n != nn:
			q = cursor.execute('UPDATE quotes SET user=? WHERE user=?',(nn, n)).rowcount
			if q > 0:
				await ctx.reply(f'Reattributed {str(q)} quote{"" if q == 1 else "s"} from {n} to {mention_or_str(n3)}.')
	await ctx.reply('Finished total attribution re-check.')

@bot.command(help="Ping the bot.")
async def ping(ctx):
	await ctx.reply(f"{ctx.author.mention} pong")
	print(f"{_dt_tostr()} Ping sent from {str(ctx.author)}.")

@bot.command(aliases=['add_quote'], brief="Add a quote by a user to the database.", help="Adds the message to the database as a quote attributed to the specified user. Will check for duplicate quotes by the same user.")
async def addquote(ctx, user, *, message):
	if len(message) == 0:
		await ctx.reply(f"The correct syntax is ```{_cpx}addquote *user* *message*```")
	else:
		author = to_user(user)
		a,b = insert_quote(author, message)
		if a:
			await ctx.reply(f"Successfully attributed quote #{b} to {mention_or_str(author)}.")
		else:
			await ctx.reply(f"Quote already exists in the database; it is #{b}.")

@bot.command(aliases=['get_quote'], brief="Retrieves a random or specified quote.", help="Retrieves a random quote by the target user (optional; any random quote if omitted), or the quote with the specified number.")
async def getquote(ctx, target=None):
	if target == None or len(target) == 0:
		cursor.execute("SELECT ROWID, user, message, date_added FROM quotes ORDER BY RANDOM() LIMIT 1")
		q = cursor.fetchone()
		if q == None:
			await ctx.reply("The database has no quotes.")
			return
	elif target.isdecimal() or (target.startswith('#') and target[1:].isdecimal()):
		num = target
		if target.startswith('#'):
			num = target[1:]
		cursor.execute("SELECT ROWID, user, message, date_added FROM quotes WHERE ROWID=? LIMIT 1", (num,))
		q = cursor.fetchone()
		if q == None:
			await ctx.reply(f"The database has no quote numbered {num}.")
			return
	else:
		user = to_user(target)
		cursor.execute("SELECT ROWID, user, message, date_added FROM quotes WHERE user=? ORDER BY RANDOM() LIMIT 1", (str(user),))
		q = cursor.fetchone()
		if q == None:
			await ctx.reply(f"The database has no quotes from {mention_or_str(user)}.")
			return
	await ctx.reply(embed=format_quote(q))

@bot.command(aliases=['del_quote'], brief="Delete a quote (restricted).", help="Deletes quote numbered <quote_number> from the database (only available to authorized users).")
@commands.is_owner()
async def delquote(ctx, quote_number):
	if quote_number == None or len(quote_number) == 0:
		await ctx.reply(f"The correct syntax is ```{_cpx}delquote *number*```")
		return
	if quote_number.isdecimal():
		cursor.execute("DELETE FROM quotes WHERE ROWID=?", (quote_number,))
		if cursor.rowcount == 1:
			await ctx.reply(f"Deleted quote #{quote_number}.")
		elif cursor.rowcount > 1:
			await ctx.reply(f"Deleted (somehow) {str(cursor.rowcount)} quotes numbered {quote_number}.")
		else:
			await ctx.reply("Can't find a quote with that number to delete.")
		db.commit()

@bot.command(aliases=["r","dice",'rolldice','roll'], brief="Roll dice.", help="Rolls the given dice and prints the result to chat. This operation passes everything following the command to the xdice package; see https://xdice.readthedocs.io/en/latest/index.html for details. This is intended to be replaced in the future.")
async def roll_dice(ctx, *, dice_string):
	result = roll(dice_string)
	embed = discord.Embed(title=f"Roll: `{dice_string}`", description=f"**Detailed Result**:\n```{result.format()}```\n **Final Result**:")
	embed.set_thumbnail(url="http://www.clker.com/cliparts/I/9/a/q/3/S/twenty-sided-dice-th.png")
	embed.set_image(url=f"https://dummyimage.com/512x128/d3/228b22&text={str(result)}")
	await ctx.reply(embed=embed)

@bot.command(aliases=["getquotes",'get_quotes_by','get_quotes'], brief=f"Retrieves all quotes (max {_max_quote_display}) by the user.", help=f"Retrieves all quotes by the specified user. If there are more than {_max_quote_display} such quotes in the database, returns {_max_quote_display} random ones.")
async def getquotesby(ctx, user):
	author = to_user(user)
	cursor.execute("SELECT ROWID, user, message, date_added FROM quotes WHERE user=? ORDER BY RANDOM() LIMIT ? ", (str(author), str(_max_quote_display)))
	res = cursor.fetchall()
	if len(res) == 0:
		await ctx.reply(f"There are no quotes attributed to {mention_or_str(author)}.")
	else:
		for q in res:
			await ctx.reply(embed=format_quote(q))

@bot.command(aliases=['num_quotes'], brief="Says how many quotes are in the database.", help="Retrieves the number of quotes and number of users in the database. If a user is specified, retrieves the number of quotes by that user.")
async def numquotes(ctx, user=None):
	if user == None or len(user) == 0:
		cursor.execute("SELECT COUNT(*) FROM quotes GROUP BY user")
		u = cursor.fetchall()
		u = [ a[0] for a in u ]
		await ctx.reply(f"There are {sum(u)} quotes in the database attributed to {len(u)} users.")
	else:
		author = to_user(user)
		cursor.execute("SELECT COUNT(*) FROM quotes WHERE user=? GROUP BY user", (str(author),))
		u = cursor.fetchall()
		if len(u) == 0:
			await ctx.reply(f"There are no quotes in the database attributed to {mention_or_str(author)}.")
		elif u[0][0] == 1:
			await ctx.reply(f"There is 1 quote in the database attributed to {mention_or_str(author)}.")
		else:
			await ctx.reply(f"There are {u[0][0]} quotes in the database attributed to {mention_or_str(author)}.")

@bot.command(aliases=['log_off'], hidden=True, brief="Logs the bot off (restricted).", help="Logs the bot off (only available to authorized users).")
@commands.check_any(commands.is_owner(), _is_guild_owner())
async def logoff(ctx):
	print(f"{_dt_tostr()} Quitting as instructed by {str(ctx.author)}.")
	db.close()
	_save_config()
	await bot.close()

@bot.command(brief="Display a random dog photo.", help="Find a random photo of a dog through https://thedogapi.com/ or https://dog.ceo/dog-api and display it in chat.")
async def dog(ctx):
	resp = json.loads(urllib.request.urlopen(_random_dog_url).read())
	if len(resp) > 0:
		await ctx.reply(resp[0]["url"])
	else:
		resp = json.loads(urllib.request.urlopen(_backup_random_dog_url).read())
		if "message" in resp:
			await ctx.reply(resp["message"])
		else:
			await ctx.reply("Dog APIs are unreachable at the moment.")

@bot.command(brief="Display a random cat photo.", help="Find a random photo of a cat through https://thecatapi.com/ and display it in chat.")
async def cat(ctx):
	resp = json.loads(urllib.request.urlopen(_random_cat_url).read())
	if len(resp) > 0:
		await ctx.reply(resp[0]["url"])
	else:
		await ctx.reply("Cat API is unreachable at the moment.")

@bot.command(brief="Pick one item from a comma-separated list.", help="Randomly selects one of the provided things, separated by commas.")
async def choose(ctx, *things):
	await ctx.reply(embed=discord.Embed(description=random.choice([ a.strip() for a in "".join(things).split(",") ])))

@bot.command(brief="Lists the ways this bot reacts", help="Explains which ways this bot reacts, in other ways than to commands.")
async def reactions(ctx):
	await ctx.reply(embed = discord.Embed(title="Bot reactions", description=(f"{_reaction_patterns['Blobbyrape']}  If you mention Blobby"
		f"\n{_reaction_patterns['HONK']}  If you mention geese"
		f"\n{_reaction_patterns['Kay']}  If you mention cooking"
		f"\n{_reaction_patterns['lee']}  If you mention eating"
		f"\n{_reaction_patterns['God']}  If you mention Brandon (sometimes)"
		f'\n{random.choice(_fruit_emoji)}  If you mention chicken'
		f'\n{_reaction_patterns["spicybeef"]}  If you mention beef'
		f'\n{_reaction_patterns["interviewplant"]}  If you mention an interview'
		f'\n{_reaction_patterns["Bombadil"]}  If you call Tom Bombadil in Russian'
		'\nA pain scale reaction if you use the format pain~*n* (where *n* is a number from 0 to 10)'
	)))

@bot.command(brief="Where you can find the show.", help=f"Lists the various places online to find information about AVPSO.\nType '{_cpx}info deprecated' for out of date information.")
async def info(ctx, param=""):
	if param.lower() == "deprecated":
		await ctx.reply(embed = discord.Embed(title = 'AVPSO (deprecated)', description = _inactive_links))
	else:
		await ctx.reply(embed = discord.Embed(title = 'AVPSO', description = _active_links))

def round_to_second(d: datetime.timedelta) -> datetime.timedelta:
	"""
	Removes any fractions of a second from the given duration.
	
	Parameters:
	
	- `d`: A duration.
	"""
	return d - (d % datetime.timedelta(seconds = 1))

@bot.command(brief="The bot's uptime.", help="The bot's current uptime.")
async def uptime(ctx):
	temp = datetime.datetime.now(dateutil.tz.UTC) - _last_connect
	await ctx.reply(embed = discord.Embed(title = f"{bot.user.name}'s uptime", description = f"Current uptime: {round_to_second(temp)}\nTotal uptime: {round_to_second(_total_uptime + temp)}"))

def _get_user_timezone(user: Union[discord.User, discord.Member], default: Optional[datetime.tzinfo] = dateutil.tz.UTC) -> Optional[datetime.tzinfo]:
	"""
	Retrieves the stored time zone for `user`, if any. Returns `default` if no time zone is stored for the user.
	
	Parameters:
	
	- `user`: The user whose time zone we are seeking.
	- `default` (default: UTC): The thing to return if no time zone is found for this user.
	"""
	tz = cursor.execute('SELECT timezone FROM users WHERE name=? LIMIT 1',(str(user),)).fetchall()
	if len(tz) == 0:
		return default
	return _tz_fromstr(tz[0][0])

@bot.command(aliases=['get_timezone','get_time_zone'], brief='Retrieve someone\'s time zone.', help='Retrieves the currently stored time zone the specified `user`. If `user` is omitted, retrieves the time zone for the user who issued the command. If the user is not in the bot\'s database, UTC is the default time zone.')
async def gettimezone(ctx, user = None):
	if user:
		target = to_user(user)
	else:
		target = ctx.author
	tz = _get_user_timezone(target, None)
	if tz:
		await ctx.reply(f'Time zone for {mention_or_str(target)} is {rrulemap._tz_tostr(tz)}')
	else:
		await ctx.reply(f'Time zone for {mention_or_str(target)} is UTC (default).')

@bot.command(aliases=['set_timezone','set_time_zone'], brief='Set someone\'s time zone (partially restricted).', help=f'Sets `user`\'s time zone to `timezone` in the bot\'s database. If `user` is omitted, sets the time zone for the user who issued the command. See {_timezone_url} for time zone names. Anyone can set their own time zone, but only authorized users can set someone else\'s time zone.')
async def settimezone(ctx, timezone, user = None):
	if user:
		target = to_user(user)
		if ctx.author.id != bot.owner_id and not (isinstance(ctx.author, discord.Member) and _pantheon in ctx.author.roles) and ctx.author != target:
			await ctx.reply(f'Only members of the pantheon, the guild owner, and the bot\'s owner can set other users\' time zones.')
			return
	else:
		target = ctx.author
	tz = _tz_fromstr(timezone)
	if tz:
		cursor.execute('INSERT INTO users(name,timezone) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET timezone=?',(str(target),rrulemap._tz_tostr(tz),rrulemap._tz_tostr(tz)))
		db.commit()
		await ctx.reply(f'Time zone for {mention_or_str(target)} is now set to {rrulemap._tz_tostr(tz)}.')
	else:
		await ctx.reply(f'Unable to interpret {timezone} as a time zone. Please see {_timezone_url} for a list of canonical names for time zones.')

def _schedule_argparse(authortz: Optional[datetime.tzinfo], *args: list[str]) -> tuple[datetime.tzinfo, datetime.datetime, datetime.datetime]:
	"""
	Parses arguments for the `schedule` command.
	
	Parameters:
	
	- `authortz`: The time zone for the author of the schedule request.
	- `args`: strings which might be parsed as a time zone, duration, or datetime.
	"""
	timezone, datetime1, datetime2, radius = None, None, None, None
	for a in args:
		if not radius and durationparse.is_duration_string(a):
			radius = durationparse.parse_duration(a)
		elif not datetime2:
			try:
				tmp = dateutil.parser.parse(a)
				if not datetime1:
					datetime1 = tmp
				else:
					datetime2 = tmp
			except dateutil.parser.ParserError:
				if not timezone:
					timezone = _tz_fromstr(a)
		elif not timezone:
			timezone = _tz_fromstr(a)
	if not timezone:
		timezone = authortz
	if radius == None:
		radius = dateutil.relativedelta.relativedelta(months=1)
	if not datetime1:
		datetime1 = datetime.datetime.now(timezone)
	if not datetime1.tzinfo:
		datetime1 = datetime1.replace(tzinfo=timezone)
	if datetime2:
		if not datetime2.tzinfo:
			datetime2 = datetime2.replace(tzinfo=timezone)
		return [ timezone ] + sorted([ datetime1, datetime2 ])
	else:
		return [ timezone ] + sorted([ datetime1 - radius, datetime1 + radius ])

@bot.command(brief="The broadcast schedule.", description=f"Displays the AVPSO schedule for the recent past and near future. `args` can contain a time zone, a duration (in ISO8601 format: https://en.wikipedia.org/wiki/ISO_8601#Durations except only whole number values may be used), and up to two datetimes; anything further will be ignored. If no time zone is specified the stored time zone of the user issuing the command will be used wherever a time zone is not otherwise specified. If a duration is not specified, 1 month will be used. If one datetime is specified it will be the middle of range for the displayed schedule with duration double the specified duration. If two datetimes are specified the former is the start and the latter the end of the range for the displayed schedule, and the duration will be ignored. If no datetimes are specified, the current date and time will be used as if it were the only datetime specified.")
async def schedule(ctx, *args):
	timezone, starttime, endtime = _schedule_argparse(_get_user_timezone(ctx.author), *args)
	today = datetime.datetime.now(timezone)
	if starttime <= today <= endtime:
		show_list = sorted(map(lambda x: [ x[0].astimezone(timezone), _showtypes.get(x[1].upper(), x[1]) ], _schedule.between(starttime, endtime) + [[today, 'Now']]))
		future = list(filter(lambda x: x > today, map(lambda x: x[0], show_list)))
		next_show = min(future) if len(future) > 0 else None
	else:
		show_list = sorted(map(lambda x: [ x[0].astimezone(timezone), _showtypes.get(x[1].upper(), x[1]) ], _schedule.between(starttime, endtime)))
		next_show = None
	await ctx.reply(embed = discord.Embed(title = f'AVPSO Schedule (TZ: {rrulemap._tz_tostr(timezone)})', description = '\n'.join([ f'{"**" if a == today else ""}{a.strftime(_timestamp_unzoned)}: {b}{"**" if a == today else ""}' for a, b in show_list ]) + ('' if next_show == None else f'\n\n{round_to_second(next_show-today)} remaining until the next show.')))

@bot.command(hidden=True, brief="Display the Goosecifix.", description="Display the Goosecifix.")
async def goosecifix(ctx):
	cursor.execute("SELECT latin FROM honcs ORDER BY RANDOM() LIMIT 1")
	embed = discord.Embed(title = cursor.fetchone()[0])
	embed.set_image(url=_goosecifix_url)
	await ctx.reply(embed=embed)

@bot.command(aliases=['add_honc'], hidden=True, brief="Adds a new HONC (restricted).", description="Adds a new HONC (only available to authorized users).")
@commands.is_owner()
async def addhonc(ctx, author, latin, english):
	user = to_user(author)
	cursor.execute("INSERT INTO honcs VALUES(?,?,?)", (latin, english, str(user)))
	db.commit()
	await ctx.reply("Done.")

def _rangeify(nums: Iterable[int]) -> list[str]:
	"""
	Collects consecutive integers into ranges and translates everything into strings.
	
	Parameters:
	
	- `nums`: The numbers we want to express as a list of ranges.
	"""
	q = sorted(nums)
	r = []
	i = 0
	while i < len(q):
		a = q[i]
		b = q[i]
		i += 1
		while i < len(q) and q[i] == b + 1:
			b = q[i]
			i += 1
		if a == b:
			r.append(f"{a}")
		else:
			r.append(f"{a}-{b}")
	return r

@bot.command(aliases=['get_quote_numbers'], brief="Lists all quote numbers by the given user.", description="Lists the quote numbers for every quote in the database by the specified user. If no user is specified, lists all users quoted in the database together with the number of quotes by that user.")
async def getquotenumbers(ctx, user=None):
	if user == None:
		cursor.execute("SELECT user, COUNT(ROWID) as numquotes FROM quotes GROUP BY user ORDER BY numquotes DESC, user ASC")
		lines = []
		for a, b in cursor.fetchall():
			c = find_user(a)
			lines.append(f"{b} quote{' is' if b == 1 else 's are'} attributed to {a if c == None else c.display_name}")
		await ctx.reply(embed = discord.Embed(title = "Quote Counts", description = "\n".join(lines)))
	else:
		author = to_user(user)
		cursor.execute("SELECT ROWID FROM quotes WHERE user=?", (str(author),))
		nums = list(itertools.chain.from_iterable(cursor.fetchall()))
		if len(nums) == 0:
			await ctx.reply(f"There are no quotes in the database by {mention_or_str(author)}.")
		else:
			await ctx.reply(embed = discord.Embed(title = f"{len(nums)} Quote{'s' if len(nums) > 1 else ''} by {author.display_name}", description = ", ".join(_rangeify(nums))))

@bot.command(aliases=['add_schedule'], brief='Add a new entry or rule to the schedule (restricted).', description='Adds `when` as a new entry in the schedule; `title` is the type of show that happens on that schedule. `when` should be either something which can be interpreted as a `datetime` using `dateutil.parser.parse` ( https://dateutil.readthedocs.io/en/stable/parser.html ) or something which can be interpreted as a recurrence rule using `dateutil.rrule.rrulestr` ( https://dateutil.readthedocs.io/en/stable/rrule.html\n`\\n` will be replaced with a newline character before interpretation). (Only available to authorized users.)')
@commands.check_any(commands.is_owner(), _is_guild_owner(), commands.has_role('The Pantheon'))
async def addschedule(ctx, when, *, title):
	try:
		qq = dateutil.parser.parse(when)
		if not qq.tzinfo:
			qq = qq.replace(tzinfo = _get_user_timezone(ctx.author))
	except dateutil.parser.ParserError:
		try:
			qq = dateutil.rrule.rrulestr(when.replace('\\n','\n'))
			if not qq._tzinfo:
				qq = qq.replace(dtstart = qq._dtstart.replace(tzinfo = _get_user_timezone(ctx.author)))
		except ValueError:
			await ctx.reply(f'Can\'t interpret {when} as either a datetime or a recurrence rule.')
			return
	_schedule.add(qq, title)
	_params['Schedule'] = pickle.dumps(_schedule).hex()
	_save_config()
	await ctx.reply(f'Added {title} on schedule {when}.')

@bot.command(aliases=['remove_schedule'], brief='Remove an entry or rule from the schedule (restricted).', description='Removes a new entry in the schedule. `when` should be either something which can be interpreted as a `datetime` using `dateutil.parser.parse` ( https://dateutil.readthedocs.io/en/stable/parser.html ) or something which can be interpreted as a recurrence rule using `dateutil.rrule.rrulestr` ( https://dateutil.readthedocs.io/en/stable/rrule.html\n`\n` will be replaced with a newline character before interpretation). (Only available to authorized users.)')
@commands.check_any(commands.is_owner(), _is_guild_owner(), commands.has_role('The Pantheon'))
async def removeschedule(ctx, when):
	try:
		qq = dateutil.parser.parse(when)
		if not qq.tzinfo:
			qq = qq.replace(tzinfo = _get_user_timezone(ctx.author))
	except dateutil.parser.ParserError:
		try:
			qq = dateutil.rrule.rrulestr(when.replace('\\n','\n'))
			if not qq._tzinfo:
				qq = qq.replace(dtstart = qq._dtstart.replace(tzinfo = _get_user_timezone(ctx.author)))
		except ValueError:
			await ctx.reply(f'Can\'t interpret {when} as either a datetime or a recurrence rule.')
			return
	_schedule.remove(qq)
	_params['Schedule'] = pickle.dumps(_schedule).hex()
	_save_config()
	await ctx.reply(f'Removed {when} from the schedule.')

@bot.command(aliases=['get_smell'], brief="Pick a smell at random.", description="Selects one smell from the list at random.")
async def getsmell(ctx):
	cursor.execute("SELECT * FROM smells ORDER BY RANDOM() LIMIT 1")
	a = cursor.fetchone()
	await ctx.reply(a[0])

@bot.command(aliases=['add_smell'], brief="Adds a smell to the list.", description="Adds a new smell to the list, if it is not already present.")
async def addsmell(ctx, *, newsmell):
	try:
		cursor.execute("INSERT INTO smells VALUES(?)",(newsmell,))
		db.commit()
		await ctx.reply("Added new smell to the list.")
	except sqlite3.IntegrityError:
		await ctx.reply("Failed to add new smell; it is already in the list.")

@bot.command(brief="Pick a random perversion.", description="Picks a random sexual fetish, kink, or paraphilia from a fixed list.\nNote: This list does not distinguish between fetishes, kinks, and paraphilias; they are each called 'perversions'.\nThis list has been gathered from the Wikipedia page on paraphilias and the following link: https://badgirlsbible.com/list-of-kinks-and-fetishes")
async def perversion(ctx, *term):
	if term is None or len(term) == 0:
		cursor.execute("SELECT name, description FROM perversions ORDER BY RANDOM() LIMIT 1")
		a = cursor.fetchall()
	else:
		cursor.execute("SELECT name, description FROM perversions WHERE LOWER(name)=?",(" ".join(term).lower(),))
		a = cursor.fetchall()
	if len(a) == 0:
		await ctx.reply("Can't find a term by that name.")
	else:
		await ctx.reply(embed=discord.Embed(title=a[0][0], description=a[0][1]))

@bot.command(aliases=['pain_scale'], brief='Display the AVPSO pain scale.', description='Displays the AVPSO pain scale in chat.')
async def painscale(ctx):
	await ctx.reply(_painscale_url)

@bot.command(aliases=['bot_source'], brief='Link to the bot\'s source code.', description='Post a link to the Github repository for this bot into the chat.')
async def botsource(ctx):
	await ctx.reply(_botsource_url)

@bot.command(brief = 'Show a random nonexistant metal album.', description = 'Randomly chooses one of the AI-generated metal albums (including band name, album title, and album cover art) from Twitter account @ai_metal_bot.')
async def metal(ctx):
	a = cursor.execute('SELECT tweetid, band, album FROM albums ORDER BY RANDOM() LIMIT 1').fetchone()
	file = discord.File(os.path.join(_album_folder, f'{a[0]}.png'), filename = 'albumcover.png')
	embed = discord.Embed(title = a[2], description = f'Band: {a[1]}')
	embed.set_image(url = 'attachment://albumcover.png')
	await ctx.reply(file = file, embed = embed)

@bot.command(hidden = True, aliases = [ 'add_abbr' ], description = 'Adds a new abbreviated form of show type to the list.', brief = 'Adds a new abbreviated form of show type to the list.')
@commands.is_owner()
async def addabbr(ctx, abbr, *, term):
	_showtypes[abbr.upper()] = term
	_save_config()
	await ctx.reply(f'Added {abbr.upper()} as an abbreviated show type for "{term}"')

@bot.command(hidden = True, aliases = [ 'get_abbr' ], brief = 'Show current abbreviated show types.', description = 'Show current abbreviated show types. If you specify an abbreviation, only shows that (if it exists).')
@commands.is_owner()
async def getabbr(ctx, abbr = None):
	if abbr == None:
		await ctx.reply(embed = discord.Embed(title = 'Current Abbreviations', description = '\n'.join(map(lambda x: f'{x}: {_showtypes[x]}', sorted(_showtypes.keys())))))
	elif abbr.upper() in _showtypes:
		await ctx.reply(f'{abbr.upper()} is an abbreviation for "{_showtypes[abbr.upper()]}"')
	else:
		await ctx.reply(f'{abbr.upper()} is not currently an abbreviation.')

@bot.command(hidden = True, aliases = [ 'del_abbr' ], description = 'Delete an abbreviated show type.', brief = 'Delete an abbreviated show type.')
@commands.is_owner()
async def delabbr(ctx, abbr):
	if abbr.upper() in _showtypes:
		del _showtypes[abbr.upper()]
		await ctx.reply(f'Deleted {abbr.upper()}.')
	else:
		await ctx.reply(f'{abbr.upper()} is not currently an abbreviation.')

@bot.command(aliases = [ 'rpg_status' ], brief = 'Status of show-related RPGs', description = 'Lists the show-related RPGs together with their current status.')
async def rpgstatus(ctx):
	await ctx.reply(embed = discord.Embed(title = 'Status of RPGs', description = '\n'.join(map(lambda x: f'*{x}* : {_rpg_status[x]}', sorted(_rpg_status.keys())))))

@bot.command(aliases = [ 'set_rpgstatus', 'set_rpg_status' ], brief = 'Set the status of a show-related RPG (restricted).', description = 'Set the status of a show-related RPG, or add it if it wasn\'t already present. If the status is set to DELETE, the RPG is deleted from the list instead. (Only available to authorized users.)\nNote: Names of RPGs are case-sensitive.')
@commands.check_any(commands.is_owner(), _is_guild_owner())
async def setrpgstatus(ctx, rpg, *, status):
	if len(status) == 0:
		await ctx.reply('RPG status is not allowed to be blank.')
	elif rpg in _rpg_status:
		if status == 'DELETE':
			del _rpg_status[rpg]
			_save_config()
			await ctx.reply(f'Deleted {rpg} from the list.')
		else:
			_rpg_status[rpg] = status
			_save_config()
			await ctx.reply(f'Changed the status of {rpg} to {status}')
	elif status == 'DELETE':
		await ctx.reply(f'There is no RPG named {rpg}, so it cannot be deleted.')
	else:
		_rpg_status[rpg] = status
		_save_config()
		await ctx.reply(f'Added {rpg} with status {status}')

@bot.command(hidden = True, aliases = [ 'op_help', 'modhelp', 'mod_help' ], description = 'List all hidden commands.', brief = 'List all hidden commands.')
@commands.check_any(commands.is_owner(), _is_guild_owner())
async def ophelp(ctx):
	await ctx.reply('```Type ~help for a list of visible commands, type ~ophelp for a list of hidden commands.\n\n' + '\n'.join(map(lambda x: f'  {x.name}\t{x.brief}', filter(lambda x: x.hidden, sorted(bot.commands, key = lambda x: x.name)))) + '```')

@bot.command(aliases = [ 'quote_search' ], brief = 'Search the quote database.', description = 'Search the quote database by content of the quotes (case-insensitive). If multiple results are found, one is returned at random unless one of the supplied terms is `--all` in which case a list of quote numbers is returned and the term `--all` is removed from the search terms. All search terms must be present in order for a given quote to be considered a result.')
async def quotesearch(ctx, *args):
	if len(args) == 0 or (len(args) == 1 and args[0].lower() == '--all'):
		await ctx.reply('You must supply search terms to conduct a search.')
	else:
		terms = [ x.lower() for x in args ]
		if '--all' in terms:
			terms.remove('--all')
			nums = list(itertools.chain.from_iterable(cursor.execute(f'SELECT ROWID FROM quotes WHERE {" AND ".join([ "LOWER(message) LIKE ?" ] * len(terms))}', list(map(lambda x: f'%{x}%', terms))).fetchall()))
			if len(nums) == 0:
				await ctx.reply('There are no quotes matching those search terms.')
			else:
				await ctx.reply(embed = discord.Embed(title = f'{len(nums)} Quote{"" if len(nums) == 1 else "s"} Matching Search Terms', description = ', '.join(_rangeify(nums))))
		else:
			q = cursor.execute(f'SELECT ROWID, user, message, date_added FROM quotes WHERE {" AND ".join([ "LOWER(message) LIKE ?" ] * len(terms))} ORDER BY RANDOM() LIMIT 1', list(map(lambda x: f'%{x}%', terms))).fetchone()
			if q:
				await ctx.reply(embed = format_quote(q))
			else:
				await ctx.reply('There are no quotes matching those search terms.')

@bot.listen('on_message')
async def do_reactions(message):
	if (message.guild != None and message.guild.name.lower() != _guildname) or message.author == bot.user:
		return
	txt = message.content.lower()
	if re.search("b[l1][o0]bby", txt):
		await message.add_reaction(_reaction_patterns["Blobbyrape"])
	if re.search("g[o0e3]{2}s[e3]", txt):
		await message.add_reaction(_reaction_patterns["HONK"])
	if re.search("br[a4]nd[o0]n", txt):
		now = datetime.datetime.now(dateutil.tz.UTC)
		global _last_brandon
		if now - _last_brandon > _brandon_frequency_cap:
			_last_brandon = now
			await message.channel.send(_brandon_url)
	if re.search("c[o0]{2}k", txt):
		await message.add_reaction(_reaction_patterns["Kay"])
	if re.search("(?:\\W|^)[e3][a4]t", txt):
		await message.add_reaction(_reaction_patterns["lee"])
	if re.search('chicken', txt):
		await message.add_reaction(random.choice(_fruit_emoji))
	if re.search('beef', txt):
		await message.add_reaction(_reaction_patterns["spicybeef"])
	if re.search('pain~[01](?:\\D|$)', txt):
		await message.add_reaction(_reaction_patterns['God'])
	if re.search('pain~[23](?:\\D|$)', txt):
		await message.add_reaction(_reaction_patterns['Hesquatch'])
	if re.search('pain~[45](?:\\D|$)', txt):
		await message.add_reaction(_reaction_patterns['Goveganmotherfuckers'])
	if re.search('pain~[67](?:\\D|$)', txt):
		await message.add_reaction(_reaction_patterns['Tim_Noah'])
	if re.search('pain~[89](?:\\D|$)', txt):
		await message.add_reaction(_reaction_patterns['Oogene'])
	if re.search('pain~10(?:\\D|$)', txt):
		await message.add_reaction(_reaction_patterns['Blobbyrape'])
	if re.search('interview', txt):
		await message.add_reaction(_reaction_patterns['interviewplant'])
	if re.search('том бомбадилло', txt):
		await message.add_reaction(_reaction_patterns['Bombadil'])

@bot.listen('on_raw_reaction_add')
async def quote_by_reaction(payload):
	user = bot.get_user(payload.user_id)
	if user == bot.user:
		return
	guild = bot.get_guild(payload.guild_id)
	channel = bot.get_channel(payload.channel_id)
	message = await channel.fetch_message(payload.message_id)
	if guild.name.lower() != _guildname:
		return
	if str(payload.emoji)[0] == "\N{Left Speech Bubble}" and discord.utils.find(lambda x: str(x)[0]=="\N{Left Speech Bubble}", message.reactions).count == 1: # '\N{Left Speech Bubble}' == '\U0001f5e8'
		if message.author == bot.user:
			await channel.send(f"{bot.user.name} will not quote itself.")
			return
		a,b = insert_quote(message.author, message.clean_content)
		if a:
			await channel.send(f"Successfully attributed quote #{b} to {message.author.mention}")
		else:
			await channel.send(f"Quote already exists in the database; it is #{b}.")

def _fetch_metal() -> None:
	"""
	Looks up and downloads all of the new randomly generated metal albums from @ai_metal_bot on Twitter, storing them in the quote database.
	"""
	raw = subprocess.check_output(['snscrape', '--jsonl', 'twitter-user', 'ai_metal_bot'])
	new_tweets = list(map(json.loads, filter(lambda x: len(x)>0, raw.split(b'\n'))))
	old_tweet_ids = list(itertools.chain(*cursor.execute('SELECT tweetid FROM albums').fetchall()))
	count = 0
	for tw in filter(lambda x: x['id'] not in old_tweet_ids, new_tweets):
		r = re.fullmatch('(?P<band>[\\w\\s]*) - (?P<album>[\\w\\s]*) https://t.co/\\w*', tw['content'])
		if bool(r) and len(tw['media']) == 1:
			with open(os.path.join(_album_folder, f'{tw["id"]}.png'), 'wb') as f:
				f.write(urllib.request.urlopen(tw['media'][0]['fullUrl']).read())
			cursor.execute('INSERT INTO albums VALUES(?,?,?)', (tw['id'], r['band'], r['album']))
			count += 1
	db.commit()
	print(f'{_dt_tostr()} Checked for new tweets: {count} new, {len(old_tweet_ids)+count} total.')

@tasks.loop(seconds=43200)
async def update_metal():
	_fetch_metal()

@update_metal.before_loop
async def before_update_metal():
	await bot.wait_until_ready()

@tasks.loop(seconds=_autosave_timer)
async def store_config():
	_save_config()

@store_config.before_loop
async def before_store_config():
	await bot.wait_until_ready()

update_metal.start()
store_config.start()
bot.run(_token)