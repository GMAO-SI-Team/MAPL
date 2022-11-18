#!/usr/bin/env python3
import argparse
import sys
import os
import csv
from collections import namedtuple
import operator
from functools import partial

from enum import Enum

SUCCESS = 0

CATEGORIES = ("IMPORT","EXPORT","INTERNAL")

"""Helper functions
lambda (anonymous) functions are simple functions (usually one line),
of the form:
    lambda x, y, z, ...: <expression of x, y, z, ...>
where 'x, y, z, ...' represents one or more arguments (It's a tuple.)
They are quite handy for processing sequences (think: list, tuples, sets)
They are used here for emitting values, as well.
"""

# Return the value
identity_emit = lambda value: value
# Return value in quotes
string_emit = lambda value: ("'" + value + "'") if value else None
# Return value in brackets
array_emit = lambda value: ('[' + value + ']') if value else None

mangle_name = lambda name: string_emit(name.replace("*","'//trim(comp_name)//'")) if name else None 
make_internal_name = lambda name: name.replace('*','') if name else None

def make_entry_emit(dictionary):
    """ Returns a emit function that looks up the value in dictionary """
    return lambda key: dictionary[key] if key in dictionary else None

# constants used for Option.DIMS
DIMS_OPTIONS = [('MAPL_DimsVertOnly', 1, 'z'), ('MAPL_DimsHorzOnly', 2, 'xy'), ('MAPL_DimsHorzVert', 3, 'xyz')]
DIMS_EMIT = make_entry_emit(dict([(alias, entry) for entry, _, alias in DIMS_OPTIONS]))
RANKS = dict([(entry, rank) for entry, rank, _ in DIMS_OPTIONS])

# emit function for Option.VLOCATION
VLOCATION_EMIT = make_entry_emit({'C': 'MAPL_VlocationCenter', 'E': 'MAPL_VlocationEdge', 'N': 'MAPL_VlocationNone'})

# emit function for Option.RESTART
RESTART_EMIT = make_entry_emit({'OPT'  : 'MAPL_RestartOptional', 'SKIP' : 'MAPL_RestartSkip',
        'REQ'  : 'MAPL_RestartRequired', 'BOOT' : 'MAPL_RestartBoot',
        'SKIPI': 'MAPL_RestartSkipInitial'})

# emit function for Option.ADD2EXPORT
ADD2EXPORT_EMIT = make_entry_emit({'T': '.true.', 'F': '.false.'})

# parent class for class Option
# defines a few methods
class OptionType(Enum):
    def __init__(self, name_key, emit = None, mandatory = False, output = True):
        self.name_key = name_key
        self.emit = emit if emit else identity_emit
        self.mandatory = mandatory
        self.output = output

    def __call__(self, value):
        return self.emit(value)

    @classmethod
    def get_mandatory_options(cls):
        return list(filter(lambda m: m.mandatory, list(cls))) 

# class for the possible options in a spec
# uses functional API for creation of members (instances) with multiple word names
Option = Enum(value = 'Option', names = {
        'SHORT_NAME': ('short_name', mangle_name, True),
        'NAME': ('short_name', mangle_name, True),
        'LONG_NAME': ('long_name', string_emit, True),
        'LONG NAME': ('long_name', string_emit, True),
        'UNITS': ('units', string_emit, True),
        'DIMS': ('dims', DIMS_EMIT, True),
        'VLOCATION': ('vlocation', VLOCATION_EMIT),
        'VLOC': ('vlocation', VLOCATION_EMIT),
        'ADD2EXPORT': ('add2export', ADD2EXPORT_EMIT),
        'ADDEXP': ('add2export', ADD2EXPORT_EMIT),
        'RESTART': ('restart', RESTART_EMIT),
        'UNGRIDDED': ('ungridded', array_emit),
        'UNGRID': ('ungridded', array_emit),
        'FRIENDLYTO': ('friendlyto', string_emit),
        'FRIEND2': ('friendlyto', string_emit),
        'PRECISION': ('precision',),
        'PREC': ('precision',),
        'NUM_SUBTILES': ('num_subtitles',),
        'NUMSUBS': ('num_subtitles',),
        'AVERAGING_INTERVAL': ('averaging_interval',),
        'AVINT': ('averaging_interval',),
        'REFRESH_INTERVAL': ('refresh_interval',),
        'HALOWIDTH': ('halowidth',),
        'DEFAULT': ('default',),
        'FIELD_TYPE': ('field_type',),
        'STAGGERING': ('staggering',),
        'ROTATION': ('rotation',),
        'DATATYPE': ('datatype',),
        'ATTR_INAMES': ('attr_inames',),
        'ATT_RNAMES': ('att_rnames',),
        'ATTR_IVALUES': ('attr_ivalues',),
        'ATTR_RVALUES': ('attr_rvalues',),
        'UNGRIDDED_NAME': ('ungridded_name',),
        'UNGRIDDED_UNIT': ('ungridded_unit',),
        'UNGRIDDED_COORDS': ('ungridded_coords',),
# these are Options that are not output but used to write 
        'CONDITION': ('condition', identity_emit, False, False),
        'COND': ('condition', identity_emit, False, False),
        'ALLOC': ('alloc', identity_emit, False, False),
        'MANGLED_NAME': ('mangled_name', mangle_name, False, False),
        'INTERNAL_NAME': ('internal_name', make_internal_name, False, False),
        'RANK': ('rank', None, False, False)
    }, type = OptionType) 
 
def relation(relop, lhs, rhs, values):
    """ Returns the result of the relop relation of lhs and rhs using values for lookups """
    l = values[lhs] if isinstance(lhs, Option) else lhs
    r = values[rhs] if isinstance(rhs, Option) else rhs
    return relop(l, r)
        
# define common relations
equals = partial(relation, operator.eq)
does_not_equal = partial(relation, operator.ne)

# simple class to group information for a condition in a Rule
# compare option value against expected, produce logical value and message
condition = namedtuple('condition', 'option rel expected message')

class Rule:
    """ rule for testing conditions on Options  """

    @classmethod
    def predicate(cls, option, rel, expected):
        return partial(rel, option, expected)

    def __init__(self, conditions, joiner = all):
        """ creates rule conditions from tuples (conditions) joined by joiner function """
        """ set the check function (rule_check) """
        joiners = {all: (' and ', False), any: (' or ', True)}

        processed_conditions = tuple([condition(option, rel, expected, message) for option, rel, expected, message in conditions]) 

        # break_on_true sets behavior one condition is met
        try:
            rule_joiner, break_on_true = joiners[joiner]
        except KeyError:
            raise ValueError("Invalid joiner")
        
        def rule_check(values):
            messages = []
            results = []
            for next_condition in processed_conditions:
                option, rel, expected, message = next_condition
                test = Rule.predicate(option, rel, expected)
                test_result = test(values)
                results.append(test_result)
                if test_result:
                    # add message and break conditionally
                    messages.append(option.name_key + " " + message) 
                    if break_on_true:
                        break
                    
            if joiner(results) == True:
                raise RuntimeError(rule_joiner.join(messages))

        self.rule = rule_check
    
    def check(self, values):
        """ run rules on Option values """
        return self.rule(values)

def check_option_values(values):

    rules = [Rule(conditions = [(Option.DIMS, equals, 'MAPL_DimsHorzVert', 'is equal to MAPL_DimsHorzVert'),
            (Option.VLOCATION, equals, 'MAPL_VlocationNone', 'is equal to MAPL_VlocationNone')], joiner = all),
            Rule([condition(Option.DIMS, equals, 'MAPL_DimsHorzOnly', 'is equal to MAPL_DimsHorzOnly'),
            condition(Option.VLOCATION, does_not_equal, 'MAPL_VlocationNone', 'is not equal to MAPL_VlocationNone')])]

    for rule in rules:
        rule.check(values)

def compute_rank(dims, ungridded):
    extra_rank = len(ungridded.strip('][').split(',')) if ungridded else 0
    return RANKS[dims] + extra_rank

def digest(specs):
    """ Set Option values from parsed specs """
    mandatory_options = Option.get_mandatory_options()
    digested_specs = dict()

    for category in specs:
        category_specs = list() # All the specs for the category
        for spec in specs[category]: # spec from list
            dims = None
            ungridded = None
            option_values = dict() # dict of option values
            for column in spec: # for spec emit value
                column_value = spec[column]
                option = Option[column.upper()] # use column name to find Option
                option_value = option(column_value) # emit value
                option_values[option] = option_value # add value to dict
                if option == Option.SHORT_NAME:
                    option_values[Option.MANGLED_NAME] = Option.MANGLED_NAME(column_value)
                    option_values[Option.INTERNAL_NAME] = Option.INTERNAL_NAME(column_value)
                elif option == Option.DIMS:
                    dims = option_value
                elif option == Option.UNGRIDDED:
                    ungridded = option_value
# MANDATORY
            for option in mandatory_options:
                if option not in option_values:
                    raise RuntimeError(option.name + " is missing from spec.")
# END MANDATORY
            option_values[Option.RANK] = compute_rank(dims, ungridded)
# CHECKS HERE
            try:
                check_option_values(option_values)
            except Exception:
                raise
# END CHECKS
            category_specs.append(option_values)
        digested_specs[category] = category_specs 

    return digested_specs
    
###############################################################
class MAPL_DataSpec:
    """Declare and manipulate an import/export/internal specs for a
       MAPL Gridded component"""

    DELIMITER = ', '
    TERMINATOR = '_RC)'

    def __init__(self, category, spec_values, indent=3):
        self.category = category
        self.indent = indent
        self.mangled_name = spec_values[Option.MANGLED_NAME]
        self.internal_name = spec_values[Option.INTERNAL_NAME]
        self.condition = spec_values.get(Option.CONDITION)
        self.spec_values = spec_values

    def newline(self):
        return "\n" + " "*self.indent

    def continue_line(self):
        return "&" + self.newline() + "& "

    def emit_specs(self):
        return self.emit_header() + self.emit_args() + self.emit_trailer(nullify=False)

    # Pointers must be declared regardless of COND status.  Deactivated
    # pointers should not be _referenced_ but such sections should still
    # compile, so we must declare the pointers
    def emit_declare_pointers(self):
        dimension = 'dimension(:' + ',:'*(self.spec_values[Option.RANK]-1) + ')'
        text = self.newline() + 'real'
        if Option.PRECISION in self.spec_values:
            kind = self.spec_values.get(Option.PRECISION)
            text = text + '(kind=' + str(kind) + ')'
        text = text +', pointer, ' + dimension + ' :: ' + self.internal_name
        return text

    def emit_get_pointers(self):
        """ Generate MAPL_GetPointer calls for the MAPL_DataSpec (self) """
        """ Creates string by joining list of generated and literal strings """
        """ including if block (emit_header) and 'alloc = value' (emit_pointer_alloc) """
        return MAPL_DataSpec.DELIMITER.join(
            [ self.emit_header() + "call MAPL_GetPointer(" + self.category,
              self.internal_name, self.mangled_name] + self.emit_pointer_alloc() +
            [ MAPL_DataSpec.TERMINATOR + self.emit_trailer(nullify=True) ] )

    def emit_pointer_alloc(self):
        EMPTY_LIST = []
        key = Option.ALLOC
        value = self.spec_values.get(key)
        if value:
            value = value.strip().lower()
            listout = [ key.name_key + '=' + get_fortran_logical(value) ] if len(value) > 0 else EMPTY_LIST
        else:
            listout = EMPTY_LIST
        return listout

    def emit_header(self):
        text = self.newline()
        condition = self.condition
        if condition:
            self.indent = self.indent + 3
            text = text + "if (" + condition + ") then" + self.newline()
        return text

    def emit_args(self):
        self.indent = self.indent + 5
        text = "call MAPL_Add" + self.category.capitalize() + "Spec(gc," + self.continue_line()
        for option in self.spec_values: #wdb idea deleteme reduce?
            if option.output:
                text = text + self.emit_arg(option)
        text = text + MAPL_DataSpec.TERMINATOR + self.newline()
        self.indent = self.indent - 5
        return text

    def emit_arg(self, option):
        value = self.spec_values.get(option)
        if value:
            text = option.name_key + "=" + value + MAPL_DataSpec.DELIMITER + self.continue_line()
        else:
            text = ''
        return text

    def emit_trailer(self, nullify=False):
        if self.condition:
            self.indent = self.indent - 3
            name = self.internal_name
            text = self.newline()
            if nullify:
                text = text + "else" + self.newline()
                text = text + "   nullify(" + name + ")" + self.newline()
            text = text + "endif" + self.newline()
        else:
            text = self.newline()
        return text

def read_specs(specs_filename):
    """Returns dict of (category: list of dict of (option name: option value) """
    def csv_record_reader(csv_reader):
        """ Read a csv reader iterator until a blank line is found. """
        prev_row_blank = True
        for row in csv_reader:
            if not (len(row) == 0):
                if row[0].startswith('#'):
                    continue
                yield [cell.strip() for cell in row]
                prev_row_blank = False
            elif not prev_row_blank:
                return

    def dataframe(reader, columns):
        """ Read a reader iterator and return a list of dictionaries, each including column name and value. """
        df = []
        for row in reader:
            df.append(dict(zip(columns, row)))
        return df

    # Python is case sensitive, so dict lookups are case sensitive.
    # The column names are Fortran identifiers, which are case insensitive.
    # So all lookups in the dict below should be converted to lowercase.
    specs = {}
    with open(specs_filename, 'r') as specs_file:
        specs_reader = csv.reader(specs_file, skipinitialspace=True,delimiter='|')
        gen = csv_record_reader(specs_reader)
        schema_version = next(gen)[0].split(' ')[1]
        component = next(gen)[0].split(' ')[1]
        while True:
            try:
                gen = csv_record_reader(specs_reader)
                category = next(gen)[0].split()[1]
                bare_columns = next(gen)
                bare_columns = [c.strip() for c in bare_columns] #wdb TODO DELETEME merge above and below
                columns = [c.upper() for c in bare_columns]
                specs[category] = dataframe(gen, columns)
            except StopIteration:
                break

    return specs

def get_fortran_logical(value_in):
    """ Return string representing Fortran logical from an input string """
    """ representing a logical value input """
    TRUE_VALUE = '.true.'
    FALSE_VALUE = '.false.'
    TRUE_VALUES = {TRUE_VALUE, 't', 'true', '.t.', 'yes', 'y', 'si', 'oui', 'sim'}
    FALSE_VALUES = {FALSE_VALUE, 'f', 'false', '.f.', 'no', 'n', 'no', 'non', 'nao'}

    try:
        if value_in is None:
            raise ValueError("'None' is not valid for get_fortran_logical.")
        if value_in.strip().lower() in TRUE_VALUES:
            val_out = TRUE_VALUE
        elif value_in.strip().lower() in FALSE_VALUES:
            val_out = FALSE_VALUE
        else:
            raise ValueError("Unrecognized logical: " + value_in)
    except Exception:
        raise

    return val_out

def header():
    """
    Returns a standard warning that can be placed at the top of each
    generated _Fortran_ include file.
    """

    return """
!                          -------------------
!                          W  A  R  N  I  N  G
!                          -------------------
!
!   This code fragment is automatically generated by MAPL_GridCompSpecs_ACG.
!   Please DO NOT edit it. Any modification made in here will be overwritten
!   next time this file is auto-generated. Instead, enter your additions
!   or deletions in the .rc file in the src tree.
!
    """

def open_with_header(filename):
    f = open(filename,'w')
    f.write(header())
    return f

#############################################
# Main program begins here
#############################################

if __name__ == "__main__":

# Process command line arguments
    parser = argparse.ArgumentParser(description='Generate import/export/internal specs for MAPL Gridded Component')
    parser.add_argument("input", action='store',
                        help="input filename")
    parser.add_argument("-n", "--name", action="store",
                        help="override default grid component name derived from input filename")
    parser.add_argument("-i", "--import_specs", action="store", nargs='?',
                        default=None, const="{component}_Import___.h",
                        help="override default output filename for AddImportSpec() code")
    parser.add_argument("-x", "--export_specs", action="store", nargs='?',
                        default=None, const="{component}_Export___.h",
                        help="override default output filename for AddExternalSpec() code")
    parser.add_argument("-p", "--internal_specs", action="store", nargs='?',
                        default=None, const="{component}_Internal___.h",
                        help="override default output filename for AddImportSpec() code")
    parser.add_argument("-g", "--get-pointers", action="store", nargs='?',
                        default=None, const="{component}_GetPointer___.h",
                        help="override default output filename for get_pointer() code")
    parser.add_argument("-d", "--declare-pointers", action="store", nargs='?',
                        const="{component}_DeclarePointer___.h", default=None,
                        help="override default output filename for pointer declaration code")
    args = parser.parse_args()

# Process blocked CSV input file
    parsed_specs = read_specs(args.input)

# Emit values
    try:
        specs = digest(parsed_specs)
    except Exception:
        raise

    if args.name:
        component = args.name
    else:
        component = os.path.splitext(os.path.basename(args.input))[0]
        component = component.replace('_Registry','')
        component = component.replace('_StateSpecs','')

# open all output files
    f_specs = {}
    for category in CATEGORIES:
        option = args.__dict__[category.lower()+"_specs"]
        if option:
            fname = option.format(component=component)
            f_specs[category] = open_with_header(fname)
        else:
            f_specs[category] = None

    if args.declare_pointers:
        f_declare_pointers = open_with_header(args.declare_pointers.format(component=component))
    else:
        f_declare_pointers = None
    if args.get_pointers:
        f_get_pointers = open_with_header(args.get_pointers.format(component=component))
    else:
        f_get_pointers = None

# Generate code from specs (processed above)
    for category in CATEGORIES:
        if category in specs:
            for spec_values in specs[category]:
                spec = MAPL_DataSpec(category.lower(), spec_values)
                if f_specs[category]:
                    f_specs[category].write(spec.emit_specs())
                if f_declare_pointers:
                    f_declare_pointers.write(spec.emit_declare_pointers())
                if f_get_pointers:
                    f_get_pointers.write(spec.emit_get_pointers())

# Close output files
    for category, f in list(f_specs.items()):
        if f:
            f.close()
    if f_declare_pointers:
        f_declare_pointers.close()
    if f_get_pointers:
        f_get_pointers.close()

    sys.exit(SUCCESS)


#options = map(Option.make, (
#    (SHORT_NAME, 'name', mangle_name, True),
#    (LONG_NAME, 'long name', string_emit, True),
#    (UNITS, string_emit, True),
#    (DIMS, {'z'  : 'MAPL_DimsVertOnly', 'xy' : 'MAPL_DimsHorzOnly', 'xyz': 'MAPL_DimsHorzVert'}),
#    ('vlocation', 'vloc', {'C': 'MAPL_VlocationCenter', 'E': 'MAPL_VlocationEdge', 'N': 'MAPL_VlocationNone'}),
#    ('add2export', 'addexp',  {'T': '.true.', 'F': '.false.'}),
#    ('restart', {'OPT'  : 'MAPL_RestartOptional', 'SKIP' : 'MAPL_RestartSkip',
#                 'REQ'  : 'MAPL_RestartRequired', 'BOOT' : 'MAPL_RestartBoot',
#                 'SKIPI': 'MAPL_RestartSkipInitial'}),
#    (UNGRIDDED, {'ungridded', 'ungrid'}, array_emit),
#    ('friendlyto', 'friend2', string_emit),
#    (PRECISION, 'prec'),
#    ('num_subtiles', 'numsubs'),
#    ('averaging_interval', 'avint'),
#    'refresh_interval',
#    'halowidth',
#    'default',
#    'field_type',
#    'staggering',
#    'rotation',
#    'datatype',
#    'attr_inames',
#    'att_rnames',
#    'attr_ivalues',
#    'attr_rvalues',
#    'ungridded_name',
#    'ungridded_unit',
#    'ungridded_coords'
#))

#class OptionType(Fields, Enum):
#
#    def __new__(cls, strcode, mandatory, emit):
#        obj = super().__new__(cls, strcode, emit, mandatory)
#        return obj
#
#    @classmethod
#    def process(t):
#        name, entries = t
#        namestr = t[0]
#        emit = t[1] if len(t) > 1 else OptionType.identity_emit
#        mandatory = t[2] if len(t) > 2 else False
#        return (name, namestr, emit, mandatory)
#
#    @classmethod
#    def process_list(lst):
#        return [OptionType.process(t) for t in names]
#        
#
#def parse_spec(spec):
#    name = spec.get(SHORT_NAME)
#    if name:
#        mangled_name = mangle_name(name)
#        internal_name = make_internal_name(name)
#    else:
#        raise Exception(SHORT_NAME + " is mandatory.")
#
#    condition = spec.get(CONDITION)
#    precision = spec.get(PRECISION)
#    dims = spec.get(DIMS)
#    ungridded = spec.get(UNGRIDDED)
#    rank = compute_rank(self.dims, self.ungridded)
#def zipdict(*dicts, fillvalue = None):
#    zd = lambda dicts_, fillvalue_: {k: tuple(d.get(k, fillvalue_) for d in dicts_) for k in dicts_[0].keys()}
#    return zd(dicts, fillvalue) if dicts else None

#option_map = {
#    Option.SHORT_NAME: Fields(mangle, True),
#    Option.LONG_NAME: Fields(string_emit, True),
#    Option.UNITS: Fields(string_emit, True),
#    Option.DIMS: Fields(DIMS_EMIT, False),
#    Option.VLOCATION: Fields(VLOCATION_EMIT, False),
#    Option.ADD2EXPORT: Fields(ADD2EXPORT_EMIT, False),
#    Option.RESTART: Fields(RESTART_EMIT, False),
#    Option.UNGRIDDED: Fields(array_emit, False),
#    Option.FRIENDLYTO: Fields(string_emit, False),
#    Option.PRECISION: Fields(identity_emit, False),
#    Option.NUM_SUBTILES: Fields(identity_emit, False),
#    Option.AVERAGING_INTERVAL: Fields(identity_emit, False),
#    Option.REFRESH_INTERVAL: Fields(identity_emit, False),
#    Option.HALOWIDTH: Fields(identity_emit, False),
#    Option.DEFAULT: Fields(identity_emit, False),
#    Option.FIELD_TYPE: Fields(identity_emit, False),
#    Option.STAGGERING: Fields(identity_emit, False),
#    Option.ROTATION: Fields(identity_emit, False),
#    Option.DATATYPE: Fields(identity_emit, False),
#    Option.ATTR_INAMES: Fields(identity_emit, False),
#    Option.ATT_RNAMES: Fields(identity_emit, False),
#    Option.ATTR_IVALUES: Fields(identity_emit, False),
#    Option.ATTR_RVALUES: Fields(identity_emit, False),
#    Option.UNGRIDDED_NAME: Fields(identity_emit, False),
#    Option.UNGRIDDED_UNIT: Fields(identity_emit, False),
#    Option.UNGRIDDED_COORDS: Fields(identity_emit, False),
#    Option.CONDITION: Fields(identity_emit, False),
#    Option.ALLOC: Fields(identity_emit, False)
#}

#def relation(relop, lhs, rhs, values):
#        l = values[lhs] if isinstance(lhs, Option) else lhs
#        r = values[rhs] if isinstance(rhs, Option) else rhs
#        return relop(l, r)
#    
#equals = partial(relation, operator.eq)
#does_not_equal = partial(relation, operator.ne)
#
#def predicate(option, rel, value):
#    return partial(rel, option, value)
#
#condition = namedtuple('condition', 'option rel value message')
#def make_rule(conditions, joiner = all):
#    joiners = {all: (' and ', False), any: (' or ', True)}
#
#    try:
#        rule_joiner, break_on_true = joiners[joiner]
#    except KeyError:
#        raise ValueError("Invalid joiner")
#
#    def check(values):
#        messages = []
#        results = []
#        for condition in conditions:
#            option, rel, value, message = condition
#            test_result = predicate(option, rel, value)(values)
#            results.append(test_result)
#            if test_result:
#                messages.append(option.name_key + " " + message) 
#                if break_on_true:
#                    break
#                
#        if joiner(results) == True:
#            raise RuntimeError(rule_joiner.join(messages))
#
#    return check

