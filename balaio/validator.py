# coding: utf-8
import re
import sys
import logging
import xml.etree.ElementTree as etree

import scieloapi

import vpipes
import utils
import notifier
import checkin
import scieloapitoolbelt
import models


logger = logging.getLogger('balaio.validator')

STATUS_OK = 'ok'
STATUS_WARNING = 'warning'
STATUS_ERROR = 'error'


class SetupPipe(vpipes.ConfigMixin, vpipes.Pipe):
    __requires__ = ['_notifier', '_scieloapi', '_sapi_tools', '_pkg_analyzer', '_issn_validator']

    def _fetch_journal_data(self, criteria):
        """
        Encapsulates the two-phase process of retrieving
        data from one journal matching the criteria.
        """
        found_journals = self._scieloapi.journals.filter(
            limit=1, **criteria)
        return self._sapi_tools.get_one(found_journals)

    def transform(self, attempt):
        """
        Adds some data that will be needed during validation
        workflow.

        `attempt` is an models.Attempt instance.
        """
        logger.debug('%s started processing %s' % (self.__class__.__name__, attempt))

        pkg_analyzer = self._pkg_analyzer(attempt.filepath)
        pkg_analyzer.lock_package()

        journal_pissn = attempt.articlepkg.journal_pissn

        if journal_pissn and self._issn_validator(journal_pissn):
            try:
                journal_data = self._fetch_journal_data(
                    {'print_issn': journal_pissn})
            except ValueError:
                # unknown pissn
                journal_data = None

        journal_eissn = attempt.articlepkg.journal_eissn
        if journal_eissn and self._issn_validator(journal_eissn) and not journal_data:
            try:
                journal_data = self._fetch_journal_data(
                    {'eletronic_issn': journal_eissn})
            except ValueError:
                # unknown eissn
                journal_data = None

        if not journal_data:
            logger.info('%s is not related to a known journal' % attempt)
            attempt.is_valid = False

        return_value = (attempt, pkg_analyzer, journal_data)
        logger.debug('%s returning %s' % (self.__class__.__name__, ','.join([repr(val) for val in return_value])))
        return return_value


class TearDownPipe(vpipes.ConfigMixin, vpipes.Pipe):
    __requires__ = ['_notifier', '_scieloapi', '_sapi_tools', '_pkg_analyzer']

    def transform(self, item):
        logger.debug('%s started processing %s' % (self.__class__.__name__, item))
        attempt, pkg_analyzer, journal_data = item

        pkg_analyzer.restore_perms()

        if attempt.is_valid:
            logger.info('Finished validating %s' % attempt)
        else:
            utils.mark_as_failed(attempt.filepath)
            logger.info('%s is invalid. Finished.' % attempt)


class PublisherNameValidationPipe(vpipes.ValidationPipe):
    """
    Validate the publisher name in article. It must be same as registered in journal data
    """
    _stage_ = 'Publisher Name Validation'
    __requires__ = ['_notifier', '_scieloapi', '_sapi_tools', '_pkg_analyzer', '_normalize_data']

    def validate(self, item):
        """
        Performs a validation to one `item` of data iterator.

        `item` is a tuple comprised of instances of models.Attempt, a
        checkin.PackageAnalyzer and a dict of journal data.
        """

        attempt, package_analyzer, journal_data = item
        j_publisher_name = journal_data.get('publisher_name', None)
        if j_publisher_name:
            data = package_analyzer.xml
            xml_publisher_name = data.findtext('.//publisher-name')

            if xml_publisher_name:
                if self._normalize_data(xml_publisher_name) == self._normalize_data(j_publisher_name):
                    r = [STATUS_OK, '']
                else:
                    r = [STATUS_ERROR, j_publisher_name + ' [journal]\n' + xml_publisher_name + ' [article]']
            else:
                r = [STATUS_ERROR, 'Missing publisher-name in article']
        else:
            r = [STATUS_ERROR, 'Missing publisher_name in journal']
        return r


class ReferenceSourceValidationPipe(vpipes.ValidationPipe):
    """
    Validate the tag source references
    Verify if exists tag source references
    Verify if exists content in tag source
    Analized tag: ``.//ref-list/ref/element-citation/source``
    """
    _stage_ = 'Reference Source Validation'
    __requires__ = ['_notifier', '_pkg_analyzer']

    def validate(self, package_analyzer):

        lst_errors = []

        refs = package_analyzer.xml.findall(".//ref-list/ref")

        if refs:
            for ref in refs:
                source = ref.find(".//source")

                if source is not None:
                    if source.text is None:
                        lst_errors.append((ref.attrib['id'], 'missing content in tag source'))
                else:
                    lst_errors.append((ref.attrib['id'], 'missing tag source'))

        else:
            return [STATUS_WARNING, 'this xml does not have reference list']

        if lst_errors:
            msg_error = 'There is some errors in refs:'

            for ref_id, msg in lst_errors:
                msg_error += ' %s: %s' % (ref_id, msg)

        return [STATUS_ERROR, msg_error] if lst_errors else [STATUS_OK, '']


class ReferenceArticleTitleValidationPipe(vpipes.ValidationPipe):
    """
    Validate the tag article-title references
    Verify if exists tag article-title references
    Verify if exists content in tag article-title
    Analized tag: ``.//ref-list/ref/element-citation/article-title``
    """
    _stage_ = 'Reference Article Title Validation'
    __requires__ = ['_notifier', '_pkg_analyzer']

    def validate(self, package_analyzer):

        lst_errors = []

        refs = package_analyzer.xml.findall(".//ref-list/ref")

        if refs:
            for ref in refs:
                article_title = ref.find(".//article-title")

                if article_title is not None:
                    if article_title.text is None:
                        lst_errors.append((ref.attrib['id'], 'missing content in tag article-title'))
                else:
                    lst_errors.append((ref.attrib['id'], 'missing tag article-title'))

        else:
            return [STATUS_WARNING, 'this xml does not have reference list']

        if lst_errors:
            msg_error = 'There is some errors in refs:'

            for ref_id, msg in lst_errors:
                msg_error += ' %s: %s' % (ref_id, msg)

        return [STATUS_ERROR, msg_error] if lst_errors else [STATUS_OK, '']


class ReferenceYearValidationPipe(vpipes.ValidationPipe):
    """
    Validate the tag year references
    Verify if exists tag year references
    Verify if exists content in tag year
    Analized tag: ``.//ref-list/ref/element-citation/year``
    """
    _stage_ = 'Reference Year Validation'
    __requires__ = ['_notifier', '_pkg_analyzer']

    def validate(self, package_analyzer):

        lst_errors = []

        refs = package_analyzer.xml.findall(".//ref-list/ref")

        if refs:
            for ref in refs:
                year = ref.find(".//year")

                if year is not None:
                    if year.text is None:
                        lst_errors.append((ref.attrib['id'], 'missing content in tag year'))
                    else:
                        if not re.search(r'\d{4}', year.text):
                            lst_errors.append((ref.attrib['id'], 'date not well format'))
                else:
                    lst_errors.append((ref.attrib['id'], 'missing tag year'))

        else:
            return [STATUS_WARNING, 'this xml does not have reference list']

        if lst_errors:
            msg_error = 'There is some errors in refs:'

            for ref_id, msg in lst_errors:
                msg_error += ' %s: %s' % (ref_id, msg)

        return [STATUS_ERROR, msg_error] if lst_errors else [STATUS_OK, '']


class JournalAbbreviatedTitleValidationPipe(vpipes.ValidationPipe):
    """
    Checks exist abbreviated title on source and xml
    Verify if abbreviated title of the xml is equal to source
    """
    _stage_ = 'Journal Abbreviated Title Validation'
    __requires__ = ['_notifier', '_pkg_analyser', '_scieloapi', '_normalize_data']

    def validate(self, item):

        attempt, pkg_analyzer, journal_data = item
        abbrev_title = journal_data.get('short_title')

        if abbrev_title:
            abbrev_title_xml = pkg_analyzer.xml.find('.//journal-meta/abbrev-journal-title[@abbrev-type="publisher"]')
            if abbrev_title_xml is not None:
                if self._normalize_data(abbrev_title) == self._normalize_data(abbrev_title_xml.text):
                    return [STATUS_OK, '']
                else:
                    return [STATUS_ERROR, 'the abbreviated title in xml is defferent from the abbreviated title in the source']
            else:
                return [STATUS_ERROR, 'missing abbreviated title in xml']
        else:
            return [STATUS_ERROR, 'missing abbreviated title in source']


class FundingGroupValidationPipe(vpipes.ValidationPipe):
    """
    Validate Funding Group according to the following rules:
    Funding group is mandatory only if there is contract number in the article,
    and this data is usually in acknowledge
    """
    _stage_ = 'Funding Group Validation'
    __requires__ = ['_notifier', '_pkg_analyzer']

    def validate(self, item):
        """
        Validate funding-group according to the following rules

        :param item: a tuple of (Attempt, PackageAnalyzer, journal_data)
        :returns: [STATUS_WARNING, ack content], if no founding-group, but Acknowledgments (ack) has number
        :returns: [STATUS_OK, founding-group content], if founding-group is present
        :returns: [STATUS_OK, ack content], if no founding-group, but Acknowledgments has no numbers
        :returns: [STATUS_WARNING, 'no funding-group and no ack'], if founding-group and Acknowledgments (ack) are absents
        """
        def _contains_number(text):
            """
            Check if it has any number

            :param text: string
            :returns: True if there is any number in text
            """
            return any((True for n in xrange(10) if str(n) in text))

        attempt, pkg_analyzer, journal_data = item

        xml_tree = pkg_analyzer.xml

        funding_nodes = xml_tree.findall('.//funding-group')

        status, description = [STATUS_OK, etree.tostring(funding_nodes[0])] if funding_nodes != [] else [STATUS_WARNING, 'no funding-group']
        if status == STATUS_WARNING:
            ack_node = xml_tree.findall('.//ack')
            ack_text = etree.tostring(ack_node[0]) if ack_node != [] else ''

            if ack_text == '':
                description = 'no funding-group and no ack'
            elif _contains_number(ack_text):
                description = ack_text + ' looks to have contract number. If so, it must be identified using funding-group'
            else:
                description = ack_text
                status = STATUS_OK

        return [status, description]


class NLMJournalTitleValidationPipe(vpipes.ValidationPipe):
    """
    Validate NLM journal title
    """
    _stage_ = 'NLM Journal Title validation'
    __requires__ = ['_notifier', '_pkg_analyzer', '_scieloapi', '_sapi_tools', '_normalize_data']

    def validate(self, item):
        """
        Validate NLM journal title

        :param item: a tuple of (Attempt, PackageAnalyzer, journal_data)
        :returns: [STATUS_OK, nlm-journal-title], if nlm-journal-title in article and in journal match
        :returns: [STATUS_OK, ''], if journal has no nlm-journal-title
        :returns: [STATUS_ERROR, nlm-journal-title in article and in journal], if nlm-journal-title in article and journal do not match.
        """
        attempt, pkg_analyzer, journal_data = item

        j_nlm_title = journal_data.get('medline_title', '')
        if j_nlm_title == '':
            status, description = [STATUS_OK, 'journal has no NLM journal title']
        else:
            xml_tree = pkg_analyzer.xml
            xml_nlm_title = xml_tree.findtext('.//journal-meta/journal-id[@journal-id-type="nlm-ta"]')

            if xml_nlm_title:
                if self._normalize_data(xml_nlm_title) == self._normalize_data(j_nlm_title):
                    status, description = [STATUS_OK, xml_nlm_title]
                else:
                    status, description = [STATUS_ERROR, j_nlm_title + ' [journal]\n' + xml_nlm_title + ' [article]']
            else:
                status, description = [STATUS_ERROR, 'Missing .//journal-meta/journal-id[@journal-id-type="nlm-ta"] in article']
        return [status, description]


class DOIVAlidationPipe(vpipes.ValidationPipe):
    """
    Verify if exists DOI in XML and if it`s validated before the CrossRef
    """

    _stage_ = 'DOI Validation'
    __requires__ = ['_notifier', '_pkg_analyzer', '_doi_validator']

    def validate(self, item):

        attempt, pkg_analyzer, journal_data = item

        doi_xml = pkg_analyzer.xml.find('.//article-id/[@pub-id-type="doi"]')

        if doi_xml is not None:
            doi = journal_data.get('doi')

            if doi == doi_xml.text:
                if self._doi_validator(doi):
                    return [STATUS_OK, '']
                else:
                    return [STATUS_WARNING, 'DOI is not valid']
            else:
                return [STATUS_ERROR, 'the DOI in xml is defferent from the DOI in the source']
        else:
            return [STATUS_WARNING, 'missing DOI in xml']


if __name__ == '__main__':
    utils.setup_logging()
    config = utils.Configuration.from_env()

    messages = utils.recv_messages(sys.stdin, utils.make_digest)
    scieloapi = scieloapi.Client(config.get('manager', 'api_username'),
                                 config.get('manager', 'api_key'))
    notifier_dep = notifier.Notifier()

    ppl = vpipes.Pipeline(SetupPipe,
                          PublisherNameValidationPipe,
                          JournalAbbreviatedTitleValidationPipe,
                          NLMJournalTitleValidationPipe,
                          FundingGroupValidationPipe,
                          DOIVAlidationPipe,
                          JournalReferenceTypeValidationPipe,
                          TearDownPipe)

    # add all dependencies to a registry-ish thing
    ppl.configure(_scieloapi=scieloapi,
                  _notifier=notifier_dep,
                  _sapi_tools=scieloapitoolbelt,
                  _pkg_analyzer=checkin.PackageAnalyzer,
                  _issn_validator=utils.is_valid_issn,
                  _doi_validator=utils.is_valid_doi,
                  _normalize_data=utils.normalize_data)

    try:
        results = [msg for msg in ppl.run(messages)]
    except KeyboardInterrupt:
        sys.exit(0)
