"""Built-in plugin *specs* — identity, ports and the shape of the settings form.

One module here per built-in plugin, holding its ``Config`` and a ``PluginSpec``
subclass with the manifest. No ``execute``: the half that does the work lives in
``process_engine/plugins/`` and subclasses the spec to add it. That seam is
what lets the designer's API generate the palette and every step form for a
plugin it is physically unable to run.

So a new plugin is two modules and two list entries — the spec here in
``BUILTIN_SPECS``, the implementation there in ``BUILTIN_PLUGINS``. Both tiers
read their own list at startup, and because the runnable class *is* this class
with behaviour added, they cannot disagree about what a step is called or what
it accepts.
"""

from .azure_blob_download import AzureBlobDownloadSpec
from .condition import ConditionSpec
from .delay import DelaySpec
from .excel_refresh import ExcelRefreshSpec
from .file_purge import FilePurgeSpec
from .for_each import ForEachSpec
from .html_table import HtmlTableSpec
from .http_request import HttpRequestSpec
from .log import LogSpec
from .mysql_execute import MySQLExecuteSpec
from .mysql_query import MySQLQuerySpec
from .s3_download import S3DownloadSpec
from .send_email import SendEmailSpec
from .send_email_ses import SendEmailSESSpec
from .transform import TransformSpec

BUILTIN_SPECS: list = [
    AzureBlobDownloadSpec,
    ConditionSpec,
    DelaySpec,
    ExcelRefreshSpec,
    FilePurgeSpec,
    ForEachSpec,
    HtmlTableSpec,
    HttpRequestSpec,
    LogSpec,
    MySQLExecuteSpec,
    MySQLQuerySpec,
    S3DownloadSpec,
    SendEmailSpec,
    SendEmailSESSpec,
    TransformSpec,
]
