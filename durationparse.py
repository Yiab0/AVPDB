# Author: Yiab
# Copyright: This module is licensed under GPL v3.0.

"""
Utility module for parsing ISO8601 duration strings. This module (in its current version) will only handle duration strings without decimal parts in any component.

Functions:

- `is_duration_string(target)`: Determine whether or not a string is in ISO8601 duration format
- `parse_duration(target)`: Actually parse a duration string into a `dateutil.relativedelta.relativedelta`
"""

__docformat__ = 'restructuredtext'

import dateutil.relativedelta
import re

duration_pattern = re.compile(r'^(?P<sign>[+-])?P(?!$)(?P<years>\d+Y)?(?P<months>\d+M)?(?P<weeks>\d+W)?(?P<days>\d+D)?(T(?!$)(?P<hours>\d+H)?(?P<minutes>\d+M)?(?P<seconds>\d+S)?)?$')

def is_duration_string(target: str) -> bool:
	"""
	Determine whether or not the supplied string can be parsed as a duration string.
	
	Parameters:
	
	- `target`: A string which may or may not be parsable as a duration
	"""
	return duration_pattern.fullmatch(target)

def parse_duration(target: str) -> dateutil.relativedelta.relativedelta:
	"""
	Translate the given string into a duration.
	
	Parameters:
	
	- `target`: The string to be translated; must be in ISO8601 duration format
	
	Exceptions:
	
	- `ValueError` raised if `not is_duration_string(target)`.
	"""
	m = duration_pattern.fullmatch(target)
	if not m:
		raise ValueError(f'String is not formatted as an ISO8601 duration: {target}')
	groups = m.groupdict('00')
	sgn = groups.pop('sign')
	for k in groups:
		groups[k] = int(groups[k][:-1])
	q = dateutil.relativedelta.relativedelta(**groups)
	if sgn == '-':
		q = -q
	return q
