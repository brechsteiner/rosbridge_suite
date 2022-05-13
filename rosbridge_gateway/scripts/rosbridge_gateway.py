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


import logging
import sys
import time
from functools import partial

import rclpy
from rclpy.node import Node
from roslibpy import Ros, Topic
from tornado.ioloop import IOLoop, PeriodicCallback


def start_hook():
    IOLoop.instance().start()


def shutdown_hook():
    IOLoop.instance().stop()


class RosServer(Ros):
    def __init__(self, id, **kw):
        self.id = id
        self.topics = []
        self.nodes = 0
        self.pub = []
        self.prev_pub = []
        self.next_pub = []
        self.sub = []
        self.prev_sub = []
        self.next_sub = []
        super(RosServer, self).__init__(**kw)


class RosTopic(Topic):
    def __init__(self, mode="pub", **kw):
        self.peers = {}
        self.mode = mode
        self.peer_subscribed = False
        super(RosTopic, self).__init__(**kw)

    def __eq__(self, other):
        if isinstance(other, RosTopic):
            return self.name == other.name
        return False

    def __hash__(self):
        return hash((self.name))


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

        self.servers = {}

        self.servers["local"] = RosServer(host=local_address, port=local_port, id="local")
        self.servers["remote"] = RosServer(host=remote_address, port=remote_port, id="remote")

        connected = False
        while not connected and self.context.ok():
            try:
                for id, server in self.servers.items():
                    server.run()
                    if server.is_connected:
                        self.get_logger().info(f"Gateway is connected to server {id}")
                        connected = True
                    else:
                        connected = False
            except OSError as e:
                self.get_logger().info(
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
        self.sys_nodes = [
            "/parameter_events",
            "/rosapi",
            "/rosapi_params",
            "/rosbridge_gateway",
            "/rosbridge_websocket",
            "/rosout",
        ]

        self.get_logger().set_level(logging.INFO)

        self.create_timer(2, self._get_statistics)
        self.create_timer(1, self._get_nodes)
        self.create_timer(1, self._update_topics)
        self.create_timer(1, self._connect_topics)

    def _get_topic_names(self, server):
        topics = []
        if server.topics:
            for topic in server.topics:
                topics.append(topic.name)
        return topics

    def _get_statistics(self):
        for server in self.servers.values():
            self.get_logger().debug(f"-----------------------------------------------------")
            self.get_logger().debug(f"topic on {server.id}: {self._get_topic_names(server)}")
            self.get_logger().debug(f"prev_pub on {server.id}: {server.prev_pub}")
            self.get_logger().debug(f"prev_sub on {server.id}: {server.prev_sub}")
            self.get_logger().debug(f"pub on {server.id}: {server.pub}")
            self.get_logger().debug(f"sub on {server.id}: {server.sub}")
            self.get_logger().debug(f"next_pub on {server.id}: {server.next_pub}")
            self.get_logger().debug(f"next_sub on {server.id}: {server.next_sub}")
            self.get_logger().debug(f"-----------------------------------------------------")

    def _get_nodes(self):
        for server in self.servers.values():
            if server.nodes == 0:
                server.pub = list(set(server.next_pub))
                server.next_pub.clear()
                server.sub = list(set(server.next_sub))
                server.next_sub.clear()
                self.get_logger().debug(f"get_nodes {server.id}")
                server.get_nodes(partial(self._get_node_details, server=server))
            else:
                self.get_logger().debug(f"wait to get_nodes {server.id}")

    def _get_node_details(self, nodes, server):
        self.get_logger().debug(f"get_node_details {server.id}|{nodes}")
        _nodes = set(nodes["nodes"]) - set(self.sys_nodes)
        server.nodes = len(_nodes)
        for node in _nodes:
            server.get_node_details(node, partial(self._update_node_details, server=server))

    def _update_node_details(self, result, server):
        self.get_logger().debug(f"update_node_details {server.id}")
        server.next_pub = list(
            set(server.next_pub).union(set(result["publishing"]) - set(self.sys_topics))
        )
        server.next_sub = list(
            set(server.next_sub).union(set(result["subscribing"]) - set(self.sys_topics))
        )
        server.nodes -= 1

    def _update_topics(self):
        for server in self.servers.values():

            prev_pub, pub = set(server.prev_pub), set(server.pub)
            for topic in prev_pub - pub:
                self.get_logger().debug(f"del pub {topic} on {server.id}")
                self._del_pub_topic(topic, server)
            for topic in pub - prev_pub:
                self.get_logger().debug(f"add pub {topic} on {server.id}")
                self._add_pub_topic(topic, server)

            prev_sub, sub = set(server.prev_sub), set(server.sub)
            for topic in prev_sub - sub:
                self.get_logger().debug(f"del sub {topic} on {server.id}")
            for topic in sub - prev_sub:
                self.get_logger().debug(f"add sub {topic} on {server.id}")

            server.prev_pub, server.prev_sub = list(pub), list(sub)

    def _add_pub_topic(self, topic, server):
        server.get_topic_type(
            topic,
            partial(self._mod_topic, name=topic, server=server, action="add", mode="pub"),
        )

    def _del_pub_topic(self, topic, server):
        server.get_topic_type(
            topic,
            partial(self._mod_topic, name=topic, server=server, action="del", mode="pub"),
        )

    def _mod_topic(self, type, name, server, action, mode):
        _topics = [t for t in server.topics if t.name == name]
        if action == "add" and not _topics:
            self.get_logger().info(f"add topic {name} on {server.id}")
            _topic = RosTopic(ros=server, name=name, message_type=type["type"], mode=mode)
            for peer in self.servers.values():
                if server is not peer:
                    _peer = RosTopic(ros=peer, name=name, message_type=type["type"], mode=mode)
                    _peer.advertise()
                _topic.peers[peer.id] = _peer
            server.topics.append(_topic)
        elif action == "del" and _topics:
            self.get_logger().info(f"del topic {name} on {server.id}")
            _topic = _topics[0]
            for peer in _topic.peers.values():
                if peer.is_advertised:
                    peer.unadvertise()
                if peer.is_subscribed:
                    peer.unsubscribe()
            if _topic.is_advertised:
                _topic.unadvertise()
            if _topic.is_subscribed:
                _topic.unsubscribe()
            server.topics.remove(_topic)

    def _connect_topics(self):
        for server in self.servers.values():
            for topic in server.topics:
                for peer in topic.peers.values():
                    if not peer.peer_subscribed and topic.name in self.servers[peer.ros.id].sub:
                        self.get_logger().info(f"subscribe {topic.name} at peer {peer.ros.id}")
                        topic.subscribe(lambda msg: peer.publish(msg))
                        peer.peer_subscribed = True
                    elif peer.peer_subscribed and topic.name not in self.servers[peer.ros.id].sub:
                        self.get_logger().info(f"unsubscribe {topic.name} at peer {peer.ros.id}")
                        topic.unsubscribe()
                        peer.peer_subscribed = False


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
