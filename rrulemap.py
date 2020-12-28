# Author: Yiab
# Copyright: This module is licensed under GPL v3.0.

"""
Extends recurrence rules from the `dateutil` package to allow for multiple non-overlapping schedules in a single class.

Classes:

- `RRuleMap`
"""

__docformat__ = 'restructuredtext'

import dateutil.rrule
import dateutil.tz
import dateutil.relativedelta
import dateutil.utils
import datetime
import itertools
import copy
from typing import Optional, Union, Any, TypeVar, Generic

_compact_timestamp = "%Y%m%dT%H%M%S" # The specific datetime format used in the string format of recurrence rules.
_maxdelta = dateutil.relativedelta.relativedelta(years=100) # Only considers datetimes between `now - _maxdelta` and `now + _maxdelta` unless otherwise specified.

KeyType = Union[datetime.datetime, dateutil.rrule.rrule]
ValueType = TypeVar('V')
ItemType = tuple[KeyType, Optional[ValueType]]

def _tz_tostr(t: Union[dateutil.tz.tzfile, dateutil.tz.tzutc, None] = None) -> Optional[str]:
	"""
	Returns the canonical `str` representation of a time zone. Returns `None` if the given time zone is not one of the specific recognized types.
	
	Parameters:
	
	- `t` (default: None): The time zone object, must be either `dateutil.tz.UTC` or an instance of `dateutil.tz.tzfile`. Interprets `None` as UTC.
	"""
	if t == dateutil.tz.UTC or t == None:
		return 'UTC'
	tzn = t._filename
	for prf in dateutil.tz.TZFILES + dateutil.tz.TZPATHS:
		tzn = tzn.removeprefix(prf)
	return tzn.lstrip('/')

def _rrule_tostr(r: dateutil.rrule.rrule, tabs: int = 0) -> str:
	"""
	Changes input `rrule` into a `str`. Essentially the same as `rrule.__str__`, except this includes time zone information for `dtstart` and translates `until` into UTC when relevant.
	
	Parameters:
	
	- `r`: The `rrule` to be represented as a string.
	- `tabs` (default: 0): All lines after the first will begin with `tabs` tab characters.
	"""
	tabstr = '\n'+'\t'*tabs
	if r._tzinfo:
		ans = str(r).replace('DTSTART:',f'DTSTART;TZID={_tz_tostr(r._tzinfo)}:')
		if r._until:
			ans = ans.replace(f'UNTIL={r._until.strftime(_compact_timestamp)}',f'UNTIL={r._until.astimezone(dateutil.tz.UTC).strftime(_compact_timestamp)}Z')
		if tabs:
			ans = ans.replace('\n',tabstr)
		return ans
	return str(r).replace('\n',tabstr)

class RRuleMap(Generic[ValueType]):
	"""
	A map of `datetime.datetime` (keys) to anything (values), where the keys can be specified using `dateutil.rrule.rrule`s as well as `datetime.datetime`s. Optional timestamp format (including time zone) can also be stored as part of this class.
	"""
	
	def __init__(self, rules: list[ItemType] = [], timestamp: Optional[str] = None) -> None:
		"""
		Initialize an instance of `RRuleMap`.
		
		Parameters:
		
		- `rules` (default: []): An initial list of rules.
		- `timestamp` (default: "[%Y-%m-%d %H:%M:%S {tz}]"): A string which can be used with `datetime.datetime.strftime` followed by `.format(tz=timezone_name)`.
		"""
		self._rulelist = copy.deepcopy(rules)
		self._timestamp = "[%Y-%m-%d %H:%M:%S {tz}]" if timestamp == None else timestamp
	
	def _datetime_tostr(self, dt: datetime.datetime) -> None:
		"""
		Represents a `datetime.datetime` as a `str` using the timestamp for this `RRuleMap`, together with canonical time zone.
		
		Parameters:
		
		- `dt`: The `datetime.datetime` to stringify.
		"""
		return dt.strftime(self._timestamp).format(tz=_tz_tostr(dt.tzinfo))
	
	@staticmethod
	def _hasdate(a: KeyType, item: datetime.datetime) -> bool:
		"""
		Determine whether or not `item` is within the rule or range specified by `a`.
		
		Parameters:
		
		- `a`: The individual `datetime.datetime` or `dateutil.rrule.rrule` in which we are searching.
		- `item`: The `datetime.datetime` we are searching for.
		"""
		if isinstance(a, datetime.datetime):
			return a == item
		elif isinstance(a, dateutil.rrule.rrule):
			return item in a
		return False
	
	def __contains__(self, item: datetime.datetime) -> bool:
		"""
		Whether or not this `RRuleMap` maps the given `item` to anything other than `None`.
		
		Parameters:
		
		- `item`: The key being sought.
		"""
		return bool(self.__getitem__(item))
	
	def between(self, dtstart: datetime.datetime, dtend: datetime.datetime) -> list[tuple[datetime.datetime, Any]]:
		"""
		Returns all items from this map between `dtstart` and `dtend` (inclusive).
		
		Parameters:
		
		- `dtstart`: The lowerbound datetime.
		- `dtend`: The upperbound datetime.
		"""
		ans = {}
		for a, b in self._rulelist:
			if isinstance(a, datetime.datetime):
				if dtstart <= a <= dtend:
					ans[a] = b
			else:
				ans.update(zip(a.between(dtstart, dtend, inc = True), itertools.repeat(b)))
		return sorted(filter(lambda x: bool(x[1]), map(list, ans.items())), key=lambda x: x[0])
	
	def __copy__(self) -> 'RRuleMap':
		"""
		Makes a copy of this `RRuleMap`. This method is supposed to return a shallow copy, but it returns a deep copy anyway.
		"""
		return RRuleMap(self._rulelist, self._timestamp)
	
	def __deepcopy__(self, memo: dict = {}) -> 'RRuleMap':
		"""
		Makes a deep copy of this `RRuleMap`.
		
		Parameters:
		
		- `memo`: A memo dictionary.
		"""
		return RRuleMap(self._rulelist, self._timestamp)
	
	def __getstate__(self) -> tuple[str, list[tuple[Union[datetime.datetime, str], Optional[ValueType]]]]:
		"""
		Used for `pickle` serialization.
		"""
		return [ self._timestamp, [ [a if isinstance(a, datetime.datetime) else _rrule_tostr(a), b] for a, b in self._rulelist ] ]
	
	def __setstate__(self, state: tuple[str, list[tuple[Union[datetime.datetime, str], Optional[ValueType]]]]) -> None:
		"""
		Used for `pickle` serialization.
		
		Parameters:
		
		- `state`: Something that was (or could have been) obtained through `RRule.__getstate__`.
		"""
		self._timestamp = state[0]
		self._rulelist = [ [a if isinstance(a, datetime.datetime) else dateutil.rrule.rrulestr(a), b] for a, b in state[1] ]
	
	def __getitem__(self, key: datetime.datetime) -> Optional[ValueType]:
		"""
		Retrieve the value associated with the given key. Returns `None` if the key is not present.
		
		Parameters:
		
		- `key`: The particular datetime being sought.
		"""
		for a, b in self._rulelist[::-1]:
			if RRuleMap._hasdate(a, key):
				return b
		return None
	
	def __str__(self) -> str:
		"""
		A human-readable (mostly) description of the current state of this `RRuleMap`.
		"""
		return '\n'.join([ f'{"Remove" if b == None else str(b)}: {self._datetime_tostr(a) if isinstance(a, datetime.datetime) else _rrule_tostr(a,1)}' for a, b in self._rulelist ])
	
	@staticmethod
	def _uncovered(target: KeyType, overlist: list[ItemType], dtrange: Union[datetime.datetime, list[datetime.datetime], None] = None) -> set[datetime.datetime]:
		"""
		Figure out which datetimes in `target` are not overridden by something in `overlist`.
		
		Parameters:
		
		- `target`: The individual key - we are trying to determine whether or not it is still relevant.
		- `overlist`: The list of items which may or may not fully or partially cover the target.
		- `dtrange` (default: `None`): Restricts the range of datetimes to consider, so that we don't have to deal with recursive reasoning or go into an infinite loop.
		
			If this is `None`, uses the range of `now - _maxdelta` to `now + _maxdelta`. If this is a single `datetime.datetime`, uses the range of `dtrange - _maxdelta` to `dtrange + _maxdelta`. If this is a pair of `datetime.datetime`s uses them as the start and end of the range. If given more than two, ignores everything past the first two.
		
		Exceptions:
		
		- `TypeError` raised if `dtrange` is not of an appropriate type.
		"""
		if dtrange == None:
			midtime = datetime.datetime.now(dateutil.tz.UTC)
			starttime, endtime = midtime - _maxdelta, midtime + _maxdelta
		elif isinstance(dtrange, datetime.datetime):
			starttime, endtime = dtrange - _maxdelta, dtrange + _maxdelta
		elif len(dtrange) >= 2:
			starttime, endtime = dtrange[:2]
		else:
			raise TypeError(f'{type(dtrange)} is not appropriate for argument `dtrange`.')
		if isinstance(target, datetime.datetime):
			if starttime <= target <= endtime:
				base = { target }
			else:
				return set()
		else:
			base = set(target.between(starttime, endtime, inc = True))
		for j in overlist:
			if isinstance(j[0], datetime.datetime):
				base.discard(j[0])
			else:
				base -= j[0].between(starttime, endtime, inc=True)
		return base
	
	def cull_covered(self) -> None:
		"""
		Remove any items which are entirely covered.
		
		Any items contained in this mapping which cannot actually be relevant because every datetime they raise is also raised by a later rule are discarded from the list to boost efficiency.
		"""
		midtime = datetime.datetime.now(dateutil.tz.UTC)
		to_remove = []
		for i in range(len(self._rulelist)-1):
			base = RRuleMap._uncovered(self._rulelist[i][0], self._rulelist[i+1:])
			if len(base) == 0:
				to_remove.append(i)
			elif not isinstance(self._rulelist[i][0], datetime.datetime) and len(base)==1:
				self._rulelist[i][0] = base.pop()
		for i in to_remove[::-1]:
			del self._rulelist[i]
		return self
	
	def add(self, key: KeyType, value: Optional[ValueType]) -> None:
		"""
		Adds a new item to this map.
		
		Parameters:
		
		- `key`: The new key.
		- `value`: The new value for every element of `key`. If `value` is `None`, this is effectively removal of `key` from this map.
		"""
		self._rulelist.append([key, value])
	
	def remove(self, key: KeyType) -> None:
		"""
		Removes the given key from this map.
		
		Parameters:
		
		- `key`: The key to be removed.
		"""
		self.add(key, None)
	
	def remove_date(self, key: Union[datetime.date, datetime.datetime], tz: datetime.tzinfo) -> None:
		"""
		Removes all entries from the given date.
		
		Parameters:
		
		- `key`: Specifies a date to remove entirely from this map.
		- `tz`: Time time zone the date is in.
		"""
		dtstart = datetime.datetime.combine(key, datetime.time(0)).replace(tzinfo=tz)
		dtend = dtstart + dateutil.relativedelta.relativedelta(days=1,seconds=-1)
		if self.between(dtstart, dtend):
			self.add(dateutil.rrule.rrule(dateutil.rrule.SECONDLY, dtstart = dtstart, until = dtend), None)
	
	def getnext(self, entrytype: Optional[ValueType] = None, dtstart: Optional[datetime.datetime] = None) -> Optional[datetime.datetime]:
		"""
		Retrieves the next non-empty entry in the map.
		
		Parameters:
		
		- `entrytype` (default: `None`): If `None`, retrieves the next entry that gives any return value. Otherwise, retrieves the next entry that gives `entrytype` as its return value.
		- `dtstart` (default: now): The datetime at which we start looking.
		"""
		if dtstart == None:
			dtstart = datetime.datetime.now(dateutil.tz.UTC)
		dtnext = dtstart + _maxdelta
		for i in range(len(self._rulelist)):
			if (entrytype != None and self._rulelist[i][1] != entrytype) or self._rulelist[i][1] == None:
				continue
			if isinstance(self._rulelist[i][0], datetime.datetime) and (dtstart <= self._rulelist[i][0] <= dtnext):
				if RRuleMap._uncovered(self._rulelist[i][0], self._rulelist[i+1:], [dtstart, dtnext]):
					dtnext = self._rulelist[i][0]
			else:
				base = RRuleMap._uncovered(self._rulelist[i][0], self._rulelist[i+1:], [dtstart, dtnext])
				if base:
					dtnext = min(base)
		if self[dtnext]:
			return dtnext
		return None
