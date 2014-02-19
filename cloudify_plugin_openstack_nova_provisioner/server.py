# vim: ts=4 sw=4 et

# TODO: in create(), use currently non-existing API to detect
#       relation types, do not filter by
#       cosmo_is_network/cosmo_is_port

import copy
import inspect
import itertools
import os
import subprocess
import sys

from novaclient import exceptions as nova_exceptions

from cloudify.decorators import operation
import cosmo_plugin_openstack_common as os_common

with_nova_client = os_common.with_nova_client

MUST_SPECIFY_NETWORK_EXCEPTION_TEXT = 'Multiple possible networks found'

@operation
@with_nova_client
def create(ctx, nova_client, **kwargs):
    """
    Creates a server. Exposes the parameters mentioned in
    http://docs.openstack.org/developer/python-novaclient/api/novaclient.v1_1
    .servers.html#novaclient.v1_1.servers.ServerManager.create
    Userdata:
        In all cases, note that userdata should not be base64 encoded,
        novaclient expects it raw.
        The 'userdata' argument under nova.instance can be one of
        the following:
        1. A string
        2. A hash with 'type: http' and 'url: ...'
    """

    # For possible changes by _maybe_transform_userdata()

    server = {
        'name': ctx.node_id
    }
    server.update(copy.deepcopy(ctx.properties['server']))

    ctx.logger.debug(
        "server.create() server before transformations: {0}".format(server))

    if server.get('nics'):
        raise ValueError("Parameter with name 'nics' must not be passed to"
                         " openstack provisioner (under host's "
                         "properties.nova.instance)".format(k))

    _maybe_transform_userdata(server)

    if ('management_network_name' in ctx.properties) and ctx.properties['management_network_name']:
        nc = os_common.NeutronClient().get(config=ctx.properties.get('neutron_config'))
        net_id = nc.cosmo_get_named('network', ctx.properties['management_network_name'])['id']
        server['nics'] = [{'net-id': net_id}]
    # print(server['nics'])

    # Sugar
    if 'image_name' in server:
        server['image'] = nova_client.images.find(name=server['image_name']).id
        del server['image_name']
    if 'flavor_name' in server:
        server['flavor'] = nova_client.flavors.find(name=server['flavor_name']).id
        del server['flavor_name']

    _fail_on_missing_required_parameters(
        server,
        ('name', 'flavor', 'image', 'key_name'),
        'server')

    # Multi-NIC by networks - start
    network_nodes_runtime_properties = ctx.capabilities.get_all().values()
    if network_nodes_runtime_properties and 'management_network_name' not in ctx.properties:
        # Known limitation
        raise RuntimeError("Nova server with multi-NIC requires 'management_network_name' which was not supplied")
    nics = [
        {'net-id': n['external_id']}
        for n in network_nodes_runtime_properties
        if neutron_client.cosmo_is_network(n['external_id'])
    ]
    if nics:
        server['nics'] = server.get('nics', []) + nics
    # Multi-NIC by networks - end

    # Multi-NIC by ports - start
    port_nodes_runtime_properties = ctx.capabilities.get_all().values()
    if port_nodes_runtime_properties and 'management_network_name' not in ctx.properties:
        # Known limitation
        raise RuntimeError("Nova server with multi-NIC requires 'management_network_name' which was not supplied")
    nics = [
        {'port-id': n['external_id']}
        for n in port_nodes_runtime_properties
        if neutron_client.cosmo_is_port(n['external_id'])
    ]
    if nics:
        server['nics'] = server.get('nics', []) + nics
    # Multi-NIC by ports - end

    ctx.logger.debug(
        "server.create() server after transformations: {0}".format(server))

    # First parameter is 'self', skipping
    params_names = inspect.getargspec(nova_client.servers.create).args[1:]

    params_default_values = inspect.getargspec(
        nova_client.servers.create).defaults
    params = dict(itertools.izip(params_names, params_default_values))

    # Fail on unsupported parameters
    for k in server:
        if k not in params:
            raise ValueError("Parameter with name '{0}' must not be passed to"
                             " openstack provisioner (under host's "
                             "properties.nova.instance)".format(k))

    for k in params:
        if k in server:
            params[k] = server[k]

    if not params['meta']:
        params['meta'] = dict({})
    params['meta']['cloudify_id'] = ctx.node_id

    ctx.logger.info("Asking Nova to create server."
                "Parameters: {0}".format(str(params)))
    ctx.logger.debug("Asking Nova to create server. All possible parameters are: "
                 "{0})".format(','.join(params.keys())))

    try:
        s = nova_client.servers.create(**params)
    except nova_exceptions.BadRequest as e:
        # ctx.logger.error(e)
        if str(e).startswith(MUST_SPECIFY_NETWORK_EXCEPTION_TEXT):
            raise RuntimeError(
                "Can not provision server: management_network_name is not "
                "specified but there are several networks that the server "
                "can be connected to."
            )
        raise RuntimeError("Nova bad request error: " + str(e))
    # os.system("nova show " + s.id)
    ctx['external_id'] = s.id

@operation
@with_nova_client
def start(ctx, nova_client, **kwargs):
    server = nova_client.servers.get(ctx.runtime_properties['external_id'])

    # ACTIVE - already started
    # BUILD - is building and will start automatically after the build.
    # HP uses 'BUILD(x)' where x is a substatus therfore the startswith usage.

    if server.status == 'ACTIVE' or server.status.startswith('BUILD'):
        start_monitor(ctx)
        return

    # Rackspace: stop, start, pause, unpause, suspend - not implemented.
    # Maybe other methods too. Calling reboot() on an instance that is
    # 'SHUTOFF' will start it.

    # SHUTOFF - powered off
    if server.status == 'SHUTOFF':
        server.reboot()
        start_monitor(ctx)
        return

    raise ValueError("openstack_host_provisioner: Can not start() "
                     "server in state {0}".format(server.status))

def start_monitor(ctx):
    command = [
        sys.executable,
        os.path.join(os.path.dirname(__file__), "monitor.py")
    ]
    ctx.logger.info('starting openstack monitoring [cmd=%s]', command)
    subprocess.Popen(command)


@with_nova_client
def delete(ctx, nova_client, **kwargs):
    server = nova_client.servers.find(id=ctx.runtime_properties['external_id'])
    server.delete()
    ctx.set_stopped()

def _fail_on_missing_required_parameters(obj, required_parameters, hint_where):
    for k in required_parameters:
        if k not in obj:
            raise ValueError(
                "Required parameter '{0}' is missing (under host's "
                "properties.{1}). Required parameters are: {2}"
                .format(k, hint_where, required_parameters))


# *** userdata handlig - start ***
userdata_handlers = {}


def userdata_handler(type_):
    def f(x):
        userdata_handlers[type_] = x
        return x
    return f


def _maybe_transform_userdata(nova_config_instance):
    """Allows userdata to be read from a file, etc, not just be a string"""
    if 'userdata' not in nova_config_instance:
        return
    if not isinstance(nova_config_instance['userdata'], dict):
        return
    ud = nova_config_instance['userdata']

    _fail_on_missing_required_parameters(
        ud,
        ('type',),
        'server.userdata')

    if ud['type'] not in userdata_handlers:
        raise ValueError("Invalid type '{0}' (under host's "
                         "properties.nova_config.instance.userdata)"
                         .format(ud['type']))

    nova_config_instance['userdata'] = userdata_handlers[ud['type']](ud)


@userdata_handler('http')
def ud_http(params):
    """ Fetches userdata using HTTP """
    import requests
    _fail_on_missing_required_parameters(
        params,
        ('url',),
        "server.userdata when using type 'http'")
    ctx.logger.info("Using userdata from URL {0}".format(params['url']))
    return requests.get(params['url']).text
# *** userdata handling - end ***
