#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""
Common functionalities for AMT Driver
"""
from xml.etree import ElementTree

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import importutils
import six

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common.i18n import _LE


pywsman = importutils.try_import('pywsman')

_SOAP_ENVELOPE = 'http://www.w3.org/2003/05/soap-envelope'

LOG = logging.getLogger(__name__)

REQUIRED_PROPERTIES = {
    'amt_address': _('IP address or host name of the node. Required.'),
    'amt_password': _('Password. Required.'),
    'amt_username': _('Username to log into AMT system. Required.'),
}
OPTIONAL_PROPERTIES = {
    'amt_protocol': _('Protocol used for AMT endpoint. one of http, https; '
                      'default is "http". Optional.'),
}
COMMON_PROPERTIES = REQUIRED_PROPERTIES.copy()
COMMON_PROPERTIES.update(OPTIONAL_PROPERTIES)

opts = [
    cfg.StrOpt('protocol',
               default='http',
               help='Protocol used for AMT endpoint, '
               'support http/https'),
]

CONF = cfg.CONF
opt_group = cfg.OptGroup(name='amt',
                         title='Options for the AMT power driver')
CONF.register_group(opt_group)
CONF.register_opts(opts, opt_group)

# TODO(lintan): More boot devices are supported by AMT, but not useful
# currently. Add them in the future.
BOOT_DEVICES_MAPPING = {
    boot_devices.PXE: 'Intel(r) AMT: Force PXE Boot',
    boot_devices.DISK: 'Intel(r) AMT: Force Hard-drive Boot',
    boot_devices.CDROM: 'Intel(r) AMT: Force CD/DVD Boot',
}
DEFAULT_BOOT_DEVICE = boot_devices.DISK

AMT_PROTOCOL_PORT_MAP = {
    'http': 16992,
    'https': 16993,
}

# ReturnValue constants
RET_SUCCESS = '0'


class Client(object):
    """AMT client.

    Create a pywsman client to connect to the target server
    """
    def __init__(self, address, protocol, username, password):
        port = AMT_PROTOCOL_PORT_MAP[protocol]
        path = '/wsman'
        self.client = pywsman.Client(address, port, path, protocol,
                                     username, password)

    def wsman_get(self, resource_uri, options=None):
        """Get target server info

        :param options: client options
        :param resource_uri: a URI to an XML schema
        :returns: XmlDoc object
        :raises: AMTFailure if get unexpected response.
        :raises: AMTConnectFailure if unable to connect to the server.
        """
        if options is None:
            options = pywsman.ClientOptions()
        doc = self.client.get(options, resource_uri)
        item = 'Fault'
        fault = xml_find(doc, _SOAP_ENVELOPE, item)
        if fault is not None:
            LOG.exception(_LE('Call to AMT with URI %(uri)s failed: '
                              'got Fault %(fault)s'),
                          {'uri': resource_uri, 'fault': fault.text})
            raise exception.AMTFailure(cmd='wsman_get')
        return doc

    def wsman_invoke(self, options, resource_uri, method, data=None):
        """Invoke method on target server

        :param options: client options
        :param resource_uri: a URI to an XML schema
        :param method: invoke method
        :param data: a XmlDoc as invoke input
        :returns: XmlDoc object
        :raises: AMTFailure if get unexpected response.
        :raises: AMTConnectFailure if unable to connect to the server.
        """
        if data is None:
            doc = self.client.invoke(options, resource_uri, method)
        else:
            doc = self.client.invoke(options, resource_uri, method, data)
        item = "ReturnValue"
        return_value = xml_find(doc, resource_uri, item).text
        if return_value != RET_SUCCESS:
            LOG.exception(_LE("Call to AMT with URI %(uri)s and "
                              "method %(method)s failed: return value "
                              "was %(value)s"),
                          {'uri': resource_uri, 'method': method,
                           'value': return_value})
            raise exception.AMTFailure(cmd='wsman_invoke')
        return doc


def parse_driver_info(node):
    """Parses and creates AMT driver info

    :param node: an Ironic node object.
    :returns: AMT driver info.
    :raises: MissingParameterValue if any required parameters are missing.
    :raises: InvalidParameterValue if any parameters have invalid values.
    """

    info = node.driver_info or {}
    d_info = {}
    missing_info = []

    for param in REQUIRED_PROPERTIES:
        value = info.get(param)
        if value:
            d_info[param[4:]] = six.binary_type(value)
        else:
            missing_info.append(param)

    if missing_info:
        raise exception.MissingParameterValue(_(
            "AMT driver requires the following to be set in "
            "node's driver_info: %s.") % missing_info)

    d_info['uuid'] = node.uuid
    param = 'amt_protocol'
    protocol = info.get(param, CONF.amt.get(param[4:]))
    if protocol not in AMT_PROTOCOL_PORT_MAP:
        raise exception.InvalidParameterValue(_("Invalid "
                "protocol %s.") % protocol)
    d_info[param[4:]] = six.binary_type(protocol)

    return d_info


def get_wsman_client(node):
    """Return a AMT Client object

    :param node: an Ironic node object.
    :returns: a Client object
    :raises: MissingParameterValue if any required parameters are missing.
    :raises: InvalidParameterValue if any parameters have invalid values.
    """
    driver_info = parse_driver_info(node)
    client = Client(address=driver_info['address'],
                    protocol=driver_info['protocol'],
                    username=driver_info['username'],
                    password=driver_info['password'])
    return client


def xml_find(doc, namespace, item):
    """Find the first element with namespace and item, in the XML doc

    :param doc: a doc object.
    :param namespace: the namespace of the element.
    :param item: the element name.
    :returns: the element object or None
    :raises: AMTConnectFailure if unable to connect to the server.
    """
    if doc is None:
        raise exception.AMTConnectFailure()
    tree = ElementTree.fromstring(doc.root().string())
    query = ('.//{%(namespace)s}%(item)s' % {'namespace': namespace,
                                             'item': item})
    return tree.find(query)
