#!/usr/bin/env python3
# Software License Agreement (BSD License)
#
# Copyright (c) 2012, Willow Garage, Inc.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
#  * Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
#  * Redistributions in binary form must reproduce the above
#    copyright notice, this list of conditions and the following
#    disclaimer in the documentation and/or other materials provided
#    with the distribution.
#  * Neither the name of Willow Garage, Inc. nor the names of its
#    contributors may be used to endorse or promote products derived
#    from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
# COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
# ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.


import sys
import time

import rclpy
from rclpy.node import Node
from roslibpy import Ros, Topic
from tornado.ioloop import IOLoop, PeriodicCallback


def start_hook():
    IOLoop.instance().start()


def shutdown_hook():
    IOLoop.instance().stop()


class RosServer(Ros):
    id = None
    sub = []
    pub = []
    # last_topics = []


class RosTopic(Topic):
    def test(self):
        print(self.name)

    # def __eq__(self, other):
    #    if isinstance(other, RosTopic):
    #        return self.name == other.name and self.message_type == other.message_type
    #    return False


class RosbridgeGatewayNode(Node):
    def __init__(self):
        super().__init__("rosbridge_gateway")

        ##################################################
        # Parameter handling                             #
        ##################################################

        # get tornado application parameters
        tornado_settings = {}
        tornado_settings["websocket_ping_interval"] = float(
            self.declare_parameter("websocket_ping_interval", 0).value
        )
        tornado_settings["websocket_ping_timeout"] = float(
            self.declare_parameter("websocket_ping_timeout", 30).value
        )
        if "--websocket_ping_interval" in sys.argv:
            idx = sys.argv.index("--websocket_ping_interval") + 1
            if idx < len(sys.argv):
                tornado_settings["websocket_ping_interval"] = float(sys.argv[idx])
            else:
                print("--websocket_ping_interval argument provided without a value.")
                sys.exit(-1)

        if "--websocket_ping_timeout" in sys.argv:
            idx = sys.argv.index("--websocket_ping_timeout") + 1
            if idx < len(sys.argv):
                tornado_settings["websocket_ping_timeout"] = float(sys.argv[idx])
            else:
                print("--websocket_ping_timeout argument provided without a value.")
                sys.exit(-1)

        remote_port = self.declare_parameter("remote_port", 9090).value
        if "--remote_port" in sys.argv:
            idx = sys.argv.index("--remote_port") + 1
            if idx < len(sys.argv):
                remote_port = int(sys.argv[idx])
            else:
                print("--remote_port argument provided without a value.")
                sys.exit(-1)
        remote_address = self.declare_parameter("remote_address", "localhost").value
        if "--remote_address" in sys.argv:
            idx = sys.argv.index("--remote_address") + 1
            if idx < len(sys.argv):
                remote_address = int(sys.argv[idx])
            else:
                print("--remote_address argument provided without a value.")
                sys.exit(-1)

        local_port = self.declare_parameter("local_port", 9091).value
        if "--local_port" in sys.argv:
            idx = sys.argv.index("--local_port") + 1
            if idx < len(sys.argv):
                local_port = int(sys.argv[idx])
            else:
                print("--local_port argument provided without a value.")
                sys.exit(-1)
        local_address = self.declare_parameter("local_address", "localhost").value
        if "--local_address" in sys.argv:
            idx = sys.argv.index("--local_address") + 1
            if idx < len(sys.argv):
                local_address = int(sys.argv[idx])
            else:
                print("--local_address argument provided without a value.")
                sys.exit(-1)

        retry_startup_delay = self.declare_parameter("retry_startup_delay", 2.0).value  # seconds.
        if "--retry_startup_delay" in sys.argv:
            idx = sys.argv.index("--retry_startup_delay") + 1
            if idx < len(sys.argv):
                retry_startup_delay = int(sys.argv[idx])
            else:
                print("--retry_startup_delay argument provided without a value.")
                sys.exit(-1)

        ##################################################
        # Done with parameter handling                   #
        ##################################################

        self.servers = []
        self.topics = []

        self.servers.append(RosServer(host=local_address, port=local_port))
        self.servers.append(RosServer(host=remote_address, port=remote_port))
        self.servers[0].id = "local"
        self.servers[1].id = "remote"

        connected = False
        while not connected and self.context.ok():
            try:
                for server in self.servers:
                    server.run()
                    if server.is_connected:
                        self.get_logger().info(f"Gateway is connected to server {server.id}")
                        connected = True
                    else:
                        connected = False
            except OSError as e:
                self.get_logger().warn(
                    "Unable to start Gateway: {} " "Retrying in {}s.".format(e, retry_startup_delay)
                )
                time.sleep(retry_startup_delay)
            else:
                self.get_logger().info(f"Gateway is connected to all servers")

        self.sys_topics = [
            "/client_count",
            "/connected_clients",
            "/parameter_events",
            "/rosout",
        ]
        self.sys_hosts = [
            "/parameter_events",
            "/rosapi",
            "/rosapi_params",
            "/rosbridge_gateway",
            "/rosbridge_websocket",
            "/rosout",
        ]

        self.create_timer(1, self._get_nodes)

    def _get_nodes(self):
        for server in self.servers:
            self.get_logger().info(f"get nodes from {server.id}")
            server.get_nodes(lambda nodes, server=server: self._get_node_details(nodes, server))
            self.get_logger().info(f"pub on {server.id}: {server.pub}")
            self.get_logger().info(f"sub on {server.id}: {server.sub}")
            # self.get_logger().info(f"svc on {server.id}: {server.svc}")

    def _get_node_details(self, nodes, server):
        for node in self._diff_array(nodes["nodes"], self.sys_hosts):
            self.get_logger().info(f"get node detail {node} from {server.id}")
            server.get_node_details(
                node, lambda details, server=server: self._update_details(details, server)
            )

    def _update_details(self, details, server):
        self.get_logger().info(f"update server details on {server.id}")
        server.pub = list(set(server.pub + details["publishing"]) - set(self.sys_topics))
        server.sub = list(set(server.sub + details["subscribing"]) - set(self.sys_topics))
        server.svc = list(set(details["services"]))

    def _redistribute_topics(self, details, server):
        last_pub = server.pub
        next_pub = self._diff_array(details["publishing"], self.sys_topics)
        for topic in self._diff_array(last_pub, next_pub):
            self.get_logger().info(f"del pub {topic} on {server.id}")
            # self._del_topic([t for t in self.topics if t.name == topic][0], server)
        for topic in self._diff_array(next_pub, last_pub):
            self.get_logger().info(f"add pub {topic} on {server.id}")
            server.get_topic_type(
                topic,
                lambda type, topic=topic, server=server: self._add_topic(
                    topic, type["type"], server
                ),
            )
        server.pub = last_pub

        last_sub = server.sub
        next_sub = self._diff_array(details["subscribing"], self.sys_topics)
        for topic in self._diff_array(last_sub, next_sub):
            self.get_logger().info(f"del sub {topic} on {server.id}")
            # self._del_topic([t for t in self.topics if t.name == topic][0], server)
        for topic in self._diff_array(next_sub, last_sub):
            self.get_logger().info(f"add sub {topic} on {server.id}")
            # self._add_topic(topic, topics["types"][topics["topics"].index(topic)], server)
        server.sub = last_sub

    def _diff_array(self, a, b):
        return [x for x in a if x not in b]

    def _diff_topics(self, topics, server):
        last = set(server.last_topics)
        next = set(topics["topics"]) - set(self.sys_topics)
        del_t = last - next
        for topic in del_t:
            self._del_topic([t for t in self.topics if t.name == topic][0], server)
        for topic in next - last - del_t:
            self._add_topic(topic, topics["types"][topics["topics"].index(topic)], server)
        server.last_topics = list(next)

    def _add_topic(self, topic_name, topic_type, server):
        self.get_logger().info(f"add topic {topic_name} type {topic_type} to {server.id}")
        self.topics.append(RosTopic(server, topic_name, topic_type))

    def _del_topic(self, topic, server):
        if topic.ros == server:
            self.get_logger().info(
                f"del topic {topic.name} type {topic.message_type} from {server.id}"
            )
            self.topics.remove(topic)


#    def _call_topics(self):
#        self.get_logger().info(f"gateway topics: {self._get_topics()}")
#        for server in self.servers:
#            self.get_logger().info(f"call topics from server {server.id}")
#            RosServer.get_topics(server, lambda t, s=server: self._diff_topics(t, s))
#
#    def _get_topics(self):
#        topics = []
#        for topic in self.topics:
#            topics.append(topic.name)
#        return topics
#

# ----------------------------------------------------------------------------------------------------------

#    def add_topics_to_list(self):
#        self.get_logger().info(f"add list...  {len(self.topics)}")
#        for server in self.servers:
#            # self.get_logger().info(f"update server topics {server.id}")
#            topics = list(
#                set(roslibpy.Ros.get_topics(server, callback=None)) - set(self.deny_topics)
#            )
#            for topic in topics:
#                if not any(element.name == topic for element in self.topics):
#                    self.get_logger().info(f"add {server.id} topic {topic} to list")
#                    _topic = roslibpy.Topic(
#                        server, topic, roslibpy.Ros.get_topic_type(server, topic)
#                    )
#                    _topic.peers = {}
#                    self.topics.append(_topic)
#
#    def remove_topics_from_list(self):
#        self.get_logger().info(f"remove list...  {len(self.topics)}")
#        for server in self.servers:
#            for topic in self.topics:
#                if topic.ros is server and topic.name not in topics:
#                    for server in topic.peers:
#                        self.get_logger().info(
#                            f"unadvertise topic {topic.name} from server {server.id}"
#                        )
#                        topic.peers[server].unadvertise()
#                    self.get_logger().info(
#                        f"remove topic {topic.name} from server {server.id}"
#                    )
#                    self.topics.remove(topic)
#

#
#        for topic in self.topics:
#            for server in self.servers:
#                if topic.ros is not server:
#                    if server not in topic.peers:
#                        self.get_logger().info(
#                            f"add peer server {server.id} to {topic.name}"
#                        )
#                        topic.peers[server] = roslibpy.Topic(server, topic.name, topic.message_type)
#                    if not topic.peers[server].is_advertised:
#                        self.get_logger().info(f"advertise {topic.name} to {server.id}")
#                        topic.peers[server].advertise()


#            if not hasattr(topic, "peer"):
#                topic.peer = roslibpy.Topic(self.remote, topic.name, topic.message_type)
#            if not topic.peer.is_advertised and topic.name in self.local_publisher:
#                self.get_logger().info(f"advertise {topic.name} to remote")
#                self.advertised_topics.append(topic.name)
#                topic.peer.advertise()
#            if not topic.is_subscribed and topic.name in self.remote_subscriber:
#                self.get_logger().info(f"topic {topic.name} is subscribed")
#                topic.subscribe(lambda msg: topic.peer.publish(msg))
#            if topic.is_subscribed and topic.name not in self.remote_subscriber:
#                self.get_logger().info(f"unsubscribe topic {topic.name} to remote")
#                topic.unsubscribe()
#            if topic.peer.is_advertised and topic.name not in self.local_publisher:
#                self.get_logger().info(f"unadvertise topic {topic.name} to remote")
#                topic.peer.unadvertise()
#                self.advertised_topics.remove(topic.name)
#                self.get_logger().info(f"remove topic {topic.name} from local topic list")
#                self.local_topics.remove(topic)


def main(args=None):
    if args is None:
        args = sys.argv

    rclpy.init(args=args)
    node = RosbridgeGatewayNode()

    spin_callback = PeriodicCallback(lambda: rclpy.spin_once(node, timeout_sec=0.01), 1)
    spin_callback.start()
    try:
        start_hook()
    except KeyboardInterrupt:
        node.get_logger().info("Exiting due to SIGINT")

    node.destroy_node()
    rclpy.shutdown()
    shutdown_hook()  # shutdown hook to stop the server


if __name__ == "__main__":
    main()
