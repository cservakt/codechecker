# -------------------------------------------------------------------------
#
#  Part of the CodeChecker project, under the Apache License v2.0 with
#  LLVM Exceptions. See LICENSE for license information.
#  SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
#
# -------------------------------------------------------------------------
"""
Helpers to parse metadata.json file.
"""

from typing import Any, Dict, Iterable, List, Optional, Set, cast
import os

from codechecker_common.logger import get_logger
from codechecker_common.util import load_json


LOG = get_logger('system')


AnalyzerStatistics = Any
AnalyzerList = List[str]
CheckCommands = List[str]
CheckDurations = List[float]
CheckerNamesView = Iterable[str]
CheckerToAnalyzer = Dict[str, str]
CodeCheckerVersion = Optional[str]
DisabledCheckers = Set[str]
EnabledCheckers = Set[str]
# Checker name to enabled status.
MetadataCheckerInfo = Dict[str, bool]
# Analyzer to checker info.
MetadataCheckers = Dict[str, MetadataCheckerInfo]


def checker_is_unavailable(
    checker_name: str,
    enabled_checkers: EnabledCheckers
) -> bool:
    """
    Returns True if the given checker is unavailable.

    We filter out checkers which start with 'clang-diagnostic-' because
    these are warnings and the warning list is not available right now.

    FIXME: using the 'diagtool' could be a solution later so the
    client can send the warning list to the server.
    """
    return not checker_name.startswith('clang-diagnostic-') and \
        enabled_checkers and checker_name not in enabled_checkers


class MetadataInfoParser:
    """ Metadata info parser. """

    def __init__(self, metadata_file_path):
        """ Initalize a metadata info parser. """
        self.cc_version: CodeCheckerVersion = None
        self.check_commands: CheckCommands = []
        self.check_durations: CheckDurations = []
        self.analyzer_statistics: AnalyzerStatistics = {}

        self.checkers: MetadataCheckers = {}
        self.enabled_checkers: EnabledCheckers = set()
        self.disabled_checkers: DisabledCheckers = set()
        self.checker_to_analyzer: CheckerToAnalyzer = {}

        self.__metadata_dict: Dict[str, Any] = {}
        if os.path.isfile(metadata_file_path):
            self.__metadata_dict = cast(Dict[str, Any],
                                        load_json(metadata_file_path, {}))

            if 'version' in self.__metadata_dict:
                self.__process_metadata_info_v2()
            else:
                self.__process_metadata_info_v1()

        self.analyzers: AnalyzerList = list(self.checkers.keys())

    def __process_metadata_checkers(self):
        """
        Get enabled/disabled checkers and a checker to analyze dictionary.
        """
        for analyzer_name, analyzer_checkers in self.checkers.items():
            for checker_name, enabled in analyzer_checkers.items():
                self.checker_to_analyzer[checker_name] = analyzer_name
                if enabled:
                    self.enabled_checkers.add(checker_name)
                else:
                    self.disabled_checkers.add(checker_name)

    def __process_metadata_info_v1(self):
        """ Set metadata information from the old version json file. """
        if 'command' in self.__metadata_dict:
            self.check_commands.append(
                ' '.join(self.__metadata_dict['command']))

        if 'timestamps' in self.__metadata_dict:
            self.check_durations.append(
                float(self.__metadata_dict['timestamps']['end'] -
                      self.__metadata_dict['timestamps']['begin']))

        # Set CodeChecker version.
        self.cc_version = \
            self.__metadata_dict.get('versions', {}).get('codechecker')

        # Set analyzer statistics.
        self.analyzer_statistics = \
            self.__metadata_dict.get('analyzer_statistics', {})

        # Get analyzer checkers.
        self.checkers = self.__metadata_dict.get('checkers', {})
        for analyzer, checkers in self.checkers.items():
            if isinstance(checkers, list):
                # Version 1 metadata files originally only stored the list of
                # enabled checkers grouped by analyzer. This was true from at
                # least September 2017
                # (commit 7254d05a8b7262e4979ac613f32d6c3e0aa0d3cc) all the
                # way to March 2020
                # (commit bd775d60950d48884b8f1dc83d8b82653b83cfa3). Before
                # the official introduction of "v2" files, in December 2019,
                # (commit 0cd28acac7d31e4a0260c147b8e803b7a36908f0) the
                # ability to store the enabled status (bool) of a checker
                # was added. However, the mismatch between the representation
                # types in old formats are causing all sorts of troubles when
                # getting the 'checkers' data structure, so instead, represent
                # the structure with the new format even for a "v1" file.
                # (See web/tests/functional/report_viewer_api)
                self.checkers[analyzer] = {checker: True
                                           for checker in checkers}
        self.__process_metadata_checkers()

    def __insert_analyzer_statistics(
        self,
        source: Dict[str, Any],
        dest: AnalyzerStatistics,
        analyzer_name: str
    ):
        """ Insert stats from source to dest of the given analyzer. """
        if not source:
            return

        if analyzer_name in dest:
            dest[analyzer_name]['failed'] += source['failed']
            dest[analyzer_name]['failed_sources'].extend(
                source.get('failed_sources', []))
            dest[analyzer_name]['successful'] += source['successful']

            # Before CodeChecker 6.16.0 the 'successful_sources' are not
            # in the metadata.
            if 'successful_sources' in dest[analyzer_name]:
                dest[analyzer_name]['successful_sources'].extend(
                    source.get('successful_sources', []))

            dest[analyzer_name]['version'].update([source['version']])
        else:
            dest[analyzer_name] = source
            dest[analyzer_name]['version'] = set([source['version']])

    def __insert_checkers(
        self,
        source: Dict[str, Any],
        dest: AnalyzerStatistics,
        analyzer_name: str
    ):
        """ Insert checkers from source to dest of the given analyzer. """
        if analyzer_name in dest:
            d_chks = dest[analyzer_name]
            for checker in source:
                if checker in d_chks and source[checker] != d_chks[checker]:
                    LOG.debug('Different checker statuses for %s', checker)
                dest[analyzer_name][checker] = source[checker]
        else:
            dest[analyzer_name] = source

    def __process_metadata_info_v2(self):
        """ Set metadata information from the new version format json file. """
        cc_versions: Set[str] = set()
        check_commands: Set[str] = set()

        tools = self.__metadata_dict.get('tools', {})
        for tool in tools:
            if tool['name'] == 'codechecker' and 'version' in tool:
                cc_versions.add(tool['version'])

            if 'command' in tool:
                check_commands.add(' '.join(tool['command']))

            if 'timestamps' in tool:
                self.check_durations.append(
                    float(tool['timestamps']['end'] -
                          tool['timestamps']['begin']))

            if 'analyzers' in tool:
                for analyzer_name, analyzer_info in tool['analyzers'].items():
                    self.__insert_analyzer_statistics(
                        analyzer_info.get('analyzer_statistics', {}),
                        self.analyzer_statistics,
                        analyzer_name)

                    self.__insert_checkers(
                        analyzer_info.get('checkers', {}),
                        self.checkers,
                        analyzer_name)
            else:
                self.__insert_analyzer_statistics(
                    tool.get('analyzer_statistics', {}),
                    self.analyzer_statistics,
                    tool['name'])

                self.__insert_checkers(tool.get('checkers', {}),
                                       self.checkers,
                                       tool['name'])

        self.check_commands = list(check_commands)

        # If multiple report directories are stored it is possible that the
        # same file is failed multiple times. For this reason we need to
        # uniqueing the list of failed / succesfully analyzed files and the
        # file number in the statistics.
        for analyzer_name, stats in self.analyzer_statistics.items():
            if 'failed_sources' in stats:
                stats['failed_sources'] = list(set(stats['failed_sources']))
                stats['failed'] = len(stats['failed_sources'])

            if 'successful_sources' in stats:
                stats['successful_sources'] = \
                    list(set(stats['successful_sources']))
                stats['successful'] = len(stats['successful_sources'])

            stats['version'] = '; '.join(stats['version'])

        # FIXME: if multiple report directories are stored created by different
        # codechecker versions there can be multiple results with OFF detection
        # status. If additional reports are stored created with cppcheck all
        # the cppcheck analyzer results will be marked with unavailable
        # detection status. To solve this problem we will return with an empty
        # checker set. This way detection statuses will be calculated properly
        # but OFF and UNAVAILABLE checker statuses will never be used.
        num_of_report_dir = self.__metadata_dict.get('num_of_report_dir', 0)
        if num_of_report_dir > 1:
            self.checkers = {}

        self.cc_version = '; '.join(cc_versions) if cc_versions else None

        self.__process_metadata_checkers()
