import os
import logging
import textwrap
from argparse import ArgumentParser, RawDescriptionHelpFormatter
from more_executors.futures import f_map

from .step import StepDecorator
from .services import FastPurgeClientService


LOG = logging.getLogger("pulp-task")
LOG_FORMAT = "%(asctime)s [%(levelname)-8s] %(message)s"


class PulpTask(object):
    """Base class for Pulp CLI tasks

    Instances for PulpTask subclass may be obtained to request a Pulp
    tasks like garbage-collect, publish etc. via CLI or entrypoints.

    This class provides a CLI parser and the pulp client. Parser is
    configured with minimal options which can be extended by subclass.
    The pulp client uses the args from cli and connects to the url
    provided in the request.
    """

    def __init__(self):
        super(PulpTask, self).__init__()

        self._args = None

        self.parser = ArgumentParser(
            description=self.description, formatter_class=RawDescriptionHelpFormatter
        )
        self._basic_args()
        self.add_args()

    @property
    def description(self):
        """Description for argument parser; shows up in generated docs.

        Defaults to the class doc string with some whitespace fixes."""

        # Doc strings are typically written having the first line starting
        # without whitespace, and all other lines starting with whitespace.
        # That would be formatted oddly when copied into RST verbatim,
        # so we'll dedent all lines *except* the first.
        split = (self.__doc__ or "<undocumented task>").splitlines(True)
        firstline = split[0]
        rest = "".join(split[1:])
        rest = textwrap.dedent(rest)
        out = "".join([firstline, rest]).strip()

        # To keep separate paragraphs, we use RawDescriptionHelpFormatter,
        # but that means we have to wrap it ourselves, so do that here.
        paragraphs = out.split("\n\n")
        chunks = ["\n".join(textwrap.wrap(p)) for p in paragraphs]
        return "\n\n".join(chunks)

    @property
    def args(self):
        """Parsed args from the cli

        returns the args if avaialble from previous parse
        else parses with defined options and return the args
        """
        if not self._args:
            self._args = self.parser.parse_args()
        return self._args

    @classmethod
    def step(cls, name):
        """A decorator to mark an instance method as a discrete workflow step.

        Marking a method as a step has effects:

        - Log messages will be produced when entering and leaving the method
        - The method can be skipped if requested by the caller (via --skip argument)

        Steps may be written as plain blocking functions, or as non-blocking
        functions which accept or return Futures.  A single Future or a list of
        Futures may be used.

        When Futures are used, the following semantics apply:

        - The step is considered *started* once *any* of the input futures has finished
        - The step is considered *failed* once *any* of the output futures has failed
        - The step is considered *finished* once *all* of the output futures have finished
        """
        return StepDecorator(name)

    def _basic_args(self):
        # minimum args required for a pulp CLI task
        self.parser.add_argument("--verbose", action="store_true", help="show logs")
        self.parser.add_argument(
            "--debug",
            action="store_true",
            help="show debug statements. " "Used along --verbose",
        )

    def _setup_logging(self):
        level = logging.INFO
        if self.args.debug:
            level = logging.DEBUG
        logging.basicConfig(level=level, format=LOG_FORMAT)

    def add_args(self):
        """Add parser options/arguments for a task

        e.g. self.parser.add_argument("option", help="help text")
        """
        # Calling super add_args if it exists allows this class and
        # Service classes to be inherited in either order without breaking.
        from_super = getattr(super(PulpTask, self), "add_args", lambda: None)
        from_super()

    def run(self):
        """Implement a specific task"""

        raise NotImplementedError()

    def main(self):
        """Main method called by the entrypoint of the task."""

        # setup the logging as required
        if self.args and self.args.verbose:
            self._setup_logging()

        self.run()
        return 0


class CDNCached(FastPurgeClientService):
    # provding CDN cache related features

    def _flush_cdn(self, repos):
        # CDN cache flush functionality to be
        # used across tasks
        if not self.fastpurge_client:
            LOG.info("CDN cache flush is not enabled.")
            return []

        def purge_repo(repo):
            to_flush = []
            for url in repo.mutable_urls:
                flush_url = os.path.join(
                    self.fastpurge_root_url, repo.relative_url, url
                )
                to_flush.append(flush_url)

            LOG.debug("Flush: %s", to_flush)
            flush = self.fastpurge_client.purge_by_url(to_flush)
            return f_map(flush, lambda _: repo)

        return [purge_repo(r) for r in repos if r.relative_url]
