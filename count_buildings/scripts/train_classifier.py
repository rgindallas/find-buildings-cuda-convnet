import inspect
import sys
from collections import defaultdict
from ConfigParser import ConfigParser
from count_buildings.scripts import get_examples_from_points
from count_buildings.scripts import get_dataset_from_examples
from count_buildings.scripts import get_batches_from_datasets
from count_buildings.scripts import get_marker_from_batches
from crosscompute.libraries import disk, script
from os.path import basename, expanduser, join


SCRIPT_BY_NAME = {
    'get_examples_from_points': get_examples_from_points.run,
    'get_dataset_from_examples': get_dataset_from_examples.run,
    'get_batches_from_datasets': get_batches_from_datasets.run,
    'get_marker_from_batches': get_marker_from_batches.run,
}
SCRIPT_NAMES = [
    'get_examples_from_points',
    'get_dataset_from_examples',
    'get_batches_from_datasets',
    'get_marker_from_batches',
]
HOME_FOLDER = expanduser('~')


def start(argv=sys.argv):
    with script.Starter(run, argv) as starter:
        starter.add_argument(
            '--configuration_path', metavar='PATH', required=True)


def run(target_folder, configuration_path):
    tasks_by_script_name = get_tasks_by_script_name(
        target_folder, configuration_path)
    for script_name in SCRIPT_NAMES:
        run_script = SCRIPT_BY_NAME[script_name]
        tasks = tasks_by_script_name[script_name]
        for task_name, task in tasks:
            task_folder = disk.make_folder(join(target_folder, task_name))
            task = trim_arguments(task, run_script)
            print_task(run_script, task_folder, task)
            value_by_key = run_script(task_folder, **task)
            print('    ' + '-' * 16)
            for k, v in value_by_key.iteritems():
                print('    %s = %s' % (k, format_value(k, v)))
            print('=' * 64)


def get_tasks_by_script_name(target_folder, configuration_path):
    tasks_by_script_name = defaultdict(list)
    variables = {
        'TARGET_FOLDER': target_folder,
    }
    config_parser = ConfigParser()
    config_parser.read(configuration_path)
    for section in config_parser.sections():
        try:
            script_name, task_name = section.split()
        except ValueError:
            sys.exit('Missing name for %s' % section)
        task = {}
        for option in config_parser.options(section):
            value = config_parser.get(section, option)
            option, value = interpret(option, value)
            task[option] = expand(option, value, variables)
        tasks_by_script_name[script_name].append((task_name, task))
    return tasks_by_script_name


def interpret(option, value):
    if option.endswith('_count'):
        value = int(value)
    elif option.endswith('_fraction'):
        value = float(value)
    elif option.endswith('_dimensions') or option.endswith('_shape'):
        value = script.parse_dimensions(value)
    elif option.endswith('_size'):
        value = script.parse_size(value)
    elif option.endswith('_name'):
        option = option.replace('_name', '_folder')
        value = join('${TARGET_FOLDER}', value)
    elif option.endswith('_names'):
        o = option.replace('_names', '_name')
        option = option.replace('_names', '_folders')
        value = [interpret(o, x)[1] for x in value.split()]
    elif option.endswith('_path'):
        value = expanduser(value)
    elif option.endswith('_paths'):
        o = option.replace('_paths', '_path')
        value = [interpret(o, x)[1] for x in value.split()]
    return option, value


def expand(option, value, variables):
    if option.endswith('_path') or option.endswith('_folder'):
        return expand_string(value, variables)
    if option.endswith('_paths') or option.endswith('_folders'):
        return [expand_string(x, variables) for x in value]
    return value


def expand_string(value, variables):
    for variable_name, variable_value in variables.iteritems():
        value = value.replace('${%s}' % variable_name, variable_value)
    return value


def trim_arguments(task, run):
    value_by_key = {}
    for argument_name in inspect.getargspec(run).args:
        try:
            value_by_key[argument_name] = task[argument_name]
        except KeyError:
            pass
    return value_by_key


def print_task(run_script, task_folder, task):
    script_name = basename(run_script.__module__.replace('.', '/'))
    script_arguments = ['--target_folder %s' % shrink_value(task_folder)]
    task_packs = sorted(task.items())
    for option, value in task_packs:
        script_arguments.append('--%s %s' % (
            option, format_value(option, value)))
    print('%s %s' % (script_name, ' '.join(script_arguments)))
    for option, value in task_packs:
        if option.endswith('_paths') or option.endswith('_folders'):
            print('    %s =' % option)
            for x in value:
                print('        %s' % shrink_value(x))
        else:
            print('    %s = %s' % (option, format_value(option, value)))


def format_value(option, value):
    if option.endswith('_dimensions'):
        return 'x'.join(str(_) for _ in value)
    if option.endswith('_shape'):
        return ','.join(str(int(_)) for _ in value)
    if option.endswith('_paths') or option.endswith('_folders'):
        return ' '.join(shrink_value(x) for x in value)
    return value


def shrink_value(value):
    if not hasattr(value, 'startswith'):
        return value
    if value.startswith(HOME_FOLDER):
        value = value.replace(HOME_FOLDER, '~')
    return value
