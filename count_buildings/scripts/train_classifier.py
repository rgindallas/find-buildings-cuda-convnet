import inspect
import sys
from collections import defaultdict
from ConfigParser import ConfigParser
from count_buildings.scripts import get_examples_from_points
from count_buildings.scripts import get_dataset_from_examples
from crosscompute.libraries import disk, script
from os.path import join, expanduser


SCRIPT_BY_NAME = {
    'get_examples_from_points': get_examples_from_points.run,
    'get_dataset_from_examples': get_dataset_from_examples.run,
}
SCRIPT_NAMES = [
    'get_examples_from_points',
    'get_dataset_from_examples',
]


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
            print_task(task_folder, task)
            # run_script(task_folder, **task)


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
    if option.endswith('_dimensions'):
        value = script.parse_dimensions(value)
    elif option.endswith('_name'):
        option = option.replace('_name', '_folder')
        value = join('${TARGET_FOLDER}', value)
    elif option.endswith('_path'):
        value = expanduser(value)
    elif option.endswith('_paths'):
        value = [expanduser(x) for x in value.split()]
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


def print_task(task_folder, task):
    print(task_folder)
    for option, value in task.iteritems():
        print('\t%s = %s' % (option, value))
