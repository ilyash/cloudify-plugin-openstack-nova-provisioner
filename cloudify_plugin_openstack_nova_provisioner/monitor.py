########
# Copyright (c) 2013 GigaSpaces Technologies Ltd. All rights reserved
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
#    * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    * See the License for the specific language governing permissions and
#    * limitations under the License.

import argparse
import time
import sys
import signal
import os
import logging

import bernhard

from cloudify.manager import set_node_started, set_node_stopped
import cosmo_plugin_openstack_common as os_common

class Reporter(object):

    def __init__(self, start, stop):
        self.start = start
        self.stop = stop

class OpenstackStatusMonitor(object):

    def __init__(self, reporter, args):
        self.reporter = reporter
        self.interval = args.monitor_interval
        self.nova = os_common.NovaClient().get(region=args.region_name)
        self.continue_running = True

    def start(self):
        while self.continue_running:
            self.report_all_servers()
            time.sleep(self.interval)

    def report_all_servers(self):
        servers = None
        try:
            servers = self.nova.servers.list()
        except Exception, e:
            sys.stderr.write("Openstack monitor error: {0}\n".format(e))

        now = int(time.time())
        for server in servers:
            self.report_server(server, now)

    def report_server(self, server, time):
        if server.status == 'ACTIVE':
            method = 'start'
        else:
            method = 'stop'
        node_id = server.metadata.get('cloudify_id')
        if node_id:
            getattr(self.reporter, method)(node_id, 'server-' + str(server.id))

    def stop(self):
        sys.stdout.write("Trying to shutdown monitor process")
        self.continue_running = False


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Monitors OpenStack hosts' statuses and sends it "
                    "to a riemann server"
    )
    parser.add_argument(
        '--monitor_interval',
        help='The interval in seconds to wait between each probe',
        default=5,
        type=int
    )
    parser.add_argument(
        '--region_name',
        help='The openstack region name',
        default=None
    )
    parser.add_argument(
        '--pid_file',
        default=None,
        help='Path to a filename that should contain the monitor process id'
    )
    return parser.parse_args()


def write_pid_file(pid_file):
    with open(pid_file, 'w') as f:
        f.write(str(os.getpid()))


def main():
    logging.basicConfig()
    args = parse_arguments()
    print("Args: {0}".format(args))
    if args.pid_file:
        write_pid_file(args.pid_file)
    reporter = Reporter(set_node_started, set_node_stopped)
    monitor = OpenstackStatusMonitor(reporter, args)

    def handle(signum, frame):
        monitor.stop()

    signal.signal(signal.SIGTERM, handle)
    signal.signal(signal.SIGINT, handle)
    signal.signal(signal.SIGQUIT, handle)

    monitor.start()


if __name__ == '__main__':
    main()

