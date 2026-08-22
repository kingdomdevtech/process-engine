"""Built-in Plugins — where a new plugin goes.

A module here plus an entry in ``BUILTIN_PLUGINS`` is the whole integration:
importing it is not enough, and a plugin missing from the list is invisible to
the designer's palette *and* to every engine host. Both read this same list, so
there is no way for the two to disagree about what can run.

The alternative is a pip package with a ``process_engine.plugins`` entry point
(see ``examples/hello-plugin``), for something on its own release cycle — but
that has to be installed on every host that executes, so prefer a built-in.
"""

from .azure_blob_download import AzureBlobDownloadPlugin
from .condition import ConditionPlugin
from .delay import DelayPlugin
from .excel_refresh import ExcelRefreshPlugin
from .file_purge import FilePurgePlugin
from .for_each import ForEachPlugin
from .html_table import HtmlTablePlugin
from .http_request import HttpRequestPlugin
from .log import LogPlugin
from .mysql_execute import MySQLExecutePlugin
from .mysql_query import MySQLQueryPlugin
from .s3_download import S3DownloadPlugin
from .send_email import SendEmailPlugin
from .send_email_ses import SendEmailSESPlugin
from .transform import TransformPlugin

BUILTIN_PLUGINS: list = [
    AzureBlobDownloadPlugin,
    ConditionPlugin,
    DelayPlugin,
    ExcelRefreshPlugin,
    FilePurgePlugin,
    ForEachPlugin,
    HtmlTablePlugin,
    HttpRequestPlugin,
    LogPlugin,
    MySQLExecutePlugin,
    MySQLQueryPlugin,
    S3DownloadPlugin,
    SendEmailPlugin,
    SendEmailSESPlugin,
    TransformPlugin,
]
