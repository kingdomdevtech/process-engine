"""Built-in Plugins.

Third-party Plugins do not belong here — ship them as drop-in files or
pip packages instead (see process_engine/registry.py).
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
