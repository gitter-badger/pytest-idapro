import idc

try:  # python3
    from multiprocessing.connection import Connection
except ImportError:  # python2
    from _multiprocessing import Connection

import threading
import platform

import logging
logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger('pytest-idapro.internal.worker')


def handle_prerequisites():
    # test pytest is installed, otherwise attempt installing
    try:
        import pytest
        del pytest
        return True
    except ImportError:
        pass

    try:
        import pip
        del pip
    except ImportError:
        log.critical("Both pytest and pip are missing from IDA environment, "
                     "execution inside IDA is impossible.")
        return False

    # handle different versions of pip
    try:
        from pip import main as pip_main
    except ImportError:
        # here be dragons
        from pip._internal import main as pip_main

    # ignoring installed six and upgrading is requried to avoid an osx bug
    # see https://github.com/pypa/pip/issues/3165 for more details
    pip_command = ['install', 'pytest']
    if platform.system() == 'Darwin':
        pip_command += ['--upgrade', '--user', '--ignore-installed', 'six']
    pip_main(pip_command)

    try:
        import pytest
        del pytest
    except ImportError:
        log.exception("pytest module unavailable after installation attempt, "
                      "cannot proceed.")
        return False

    return True


class IdaWorker(threading.Thread):
    def __init__(self, conn_fd, *args, **kwargs):
        super(IdaWorker, self).__init__(*args, **kwargs)
        self.conn = Connection(conn_fd)
        self.stop = False
        self.pytest_config = None

    def run(self):
        try:
            while not self.stop:
                command = self.conn.recv()
                response = self.handle_command(*command)
                self.conn.send(response)
        except RuntimeError:
            log.exception("Runtime error encountered during message handling")
        except EOFError:
            log.info("remote connection closed abruptly, terminating.")

    def handle_command(self, command, *command_args):
        handler_name = "command_" + command
        if not hasattr(self, handler_name):
            raise RuntimeError("Unrecognized command recieved: "
                               "'{}'".format(command))
        log.debug("Received command: {} with args {}".format(command,
                                                             command_args))
        response = getattr(self, handler_name)(*command_args)
        log.debug("Responding: {}".format(response))
        return response

    def command_configure(self, args, option_dict):
        from _pytest.config import Config

        self.pytest_config = Config.fromdictargs(option_dict, args)
        self.pytest_config.option.looponfail = False
        self.pytest_config.option.usepdb = False
        self.pytest_config.option.dist = "no"
        self.pytest_config.option.distload = False
        self.pytest_config.option.numprocesses = None

        return ("configured",)

    def command_cmdline_main(self):
        self.pytest_config.hook.pytest_cmdline_main(config=self.pytest_config)

        return ("cmdline_mained",)

    @staticmethod
    def command_ping():
        return ("pong",)

    def command_quit(self):
        self.stop = True
        return ("quitting",)


def main():
    import os
    import sys
    sys.path.append(os.getcwd())

    if not handle_prerequisites():
        return

    # TODO: use idc.ARGV with some option parsing package

    worker = IdaWorker(int(idc.ARGV[1]))
    worker.start()


if __name__ == '__main__':
    # TODO: wait until auto-analysis is done
    main()
    # TODO: quit IDA