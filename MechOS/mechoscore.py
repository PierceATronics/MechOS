'''
Author: David Pierce Walker-Howell<piercedhowell@gmail.com>
Last Modified: 08/08/2019
Description:
'''
import socket
import threading
from xmlrpc.server import SimpleXMLRPCServer
from xmlrpc.server import SimpleXMLRPCRequestHandler
import xmlrpc.client
import os
import signal
import atexit
import threading
from MechOS import parameter_server
import argparse

class Mechoscore:
    '''
    Mechoscore containts and xmlrpc server that nodes, publishers,
    subscribers register to in order to hop on the mechos network.
    '''

    def __init__(self, ip="127.0.0.1", core_port=5959, param_server_port=8000):
        '''
        Initialize the XMLRPCServer.

        Parameters:
            ip: The ip address to host the XMLRPCServer. Default "http://127.0.0.101"
            core_port: The port to host the mechoscore XMLRPCServer. Default 5959
            param_server_port: The port to host the parameter server on. Default 8000

        Returns:
            N/A
        '''
        self.xmlrpc_server = SimpleXMLRPCServer((ip,core_port), logRequests=False)

        self.ip = ip
        self.core_port = core_port
        self.param_server_port = param_server_port

        #Register functions that nodes will call to register themselves as well
        #as there publishers and subscribers.
        self.xmlrpc_server.register_function(self.register_node)
        self.xmlrpc_server.register_function(self.unregister_node)
        self.xmlrpc_server.register_function(self.register_publisher)
        self.xmlrpc_server.register_function(self.register_subscriber)

        self.node_information = {}

        #When a new node is created, a client to that nodes xml rpc will be created.
        self.xmlrpc_clients_to_nodes = {}

        #Initialize the parameter server
        self.param_server = parameter_server.Parameter_Server(ip=self.ip, port=self.param_server_port)


        #At the exit of the mechoscore, unregister and kill all nodes if any are running.
        atexit.register(self.unregister_all_nodes)

    def register_node(self, name, pid, xmlrpc_server_ip, xmlrpc_server_port):
        '''
        Register a node with mechoscore. Check if that node is already created.
        If it is already created, send an error message and do not let it connect.

        Parameters:
            node_name: The name of the node to be created.
            pid: The process id of the node.
            xmlrpc_server_ip: The ip address that the node is running on.
            xmlrpc_server_port: The port that the node is running on.

        Returns:
            True: If the node can be created.
            False: If the node name already exists, then it cant be created.
        '''
        if(name in self.node_information.keys()):
            return False

        #Create an xmlrpc client to the newly registered node. This is so that
        #mechoscore can make calls to the individual nodes.
        self.xmlrpc_clients_to_nodes[name] = xmlrpc.client.ServerProxy("http://" + \
                    xmlrpc_server_ip + ":" + \
                    str(xmlrpc_server_port))

        self.node_information[name] = {"pid":pid,
                                                    "xmlrpc_server_ip": xmlrpc_server_ip,
                                                    "xmlrpc_server_port":xmlrpc_server_port,
                                                    "publishers":{},
                                                    "subscribers":{}}
        print("[INFO]: Registering Node %s to the mechos network" % name)
        return True

    def unregister_all_nodes(self):
        '''
        Unregister and kill all nodes in the mechos network

        Parameters:
            N/A
        Returns:
            N/A
        '''
        print("[WARNING]: Unregistering all Node from mechos network")
        node_names = list(self.node_information.keys()).copy()
        for node_name in node_names:
            self.unregister_node(node_name)

    def unregister_node(self, name):
        '''
        Unregister a node with mechoscore. Before a node is killed, it should
        call this in order to unregister it. Also kill the node.

        Parameters:
            node_name: The name of the node to unregister.
        Returns:
            N/A
        '''

        #Remove the information about a node.
        node_information = self.node_information[name]


        #Kill the publishers of the node
        for publisher_id in node_information["publishers"].keys():

            #For each of the nodes in the network, see if the publisher connects to
            #any subscribers. Disconnect the publisher from ALL subscribers it connects to.
            #Also tell the subscribers that they no longer need to look for messages coming
            #from this publisher.
            for node_name in self.node_information.keys():

                #Go into the nodes that have subscribers connected to the current publisher being killed.
                #Make the sockets of the subscribers disconnect from this publisher.
                self.xmlrpc_clients_to_nodes[node_name]._kill_subscriber_connection(publisher_id)

            self.xmlrpc_clients_to_nodes[name]._kill_publisher(publisher_id)

        #Kill the subscriber of the node.
        for subscriber_id in node_information["subscribers"].keys():

            #For each of the nodes in the network, see if the subscriber subscribes to
            #to any publishers of other nodes. Make it so that the publishers no longer
            #need to try and send messages to the current subscriber being killed.
            for node_name in self.node_information.keys():

                #Go into the nodes that have a publisher sending to the current subscriber being killed.
                #Make the sockets of thos publishers disconnect from sending data to te subscriber
                #being killed.
                self.xmlrpc_clients_to_nodes[node_name]._kill_publisher_connection(subscriber_id)

            self.xmlrpc_clients_to_nodes[name]._kill_subscriber(subscriber_id)

        print("[WARNING]: Unregistering and killing the process continaing Node %s" % name)
        self.node_information.pop(name)
        #self.xmlrpc_clients_to_nodes[name]._kill_node()



        return(True)
    def register_publisher(self, node_name, id, topic, ip, port, protocol):
        '''
        Register a publisher from a node. Check if the publisher has an allowable
        ip and port.

        Parameters:
            node_name: The name of the node registering the publisher
            id: The unique id of the publisher
            topic: The topic name that the publisher will publish data to.
            ip: The ip address that the publisher want to send on.
            port: The port that the publisher wants to send on.
            protocol: Either tcp or udp.
        '''

        self.node_information[node_name]["publishers"][id] = {"topic":topic,
                                                         "ip":ip,
                                                         "port":port,
                                                         "protocol":protocol}

        self.new_publisher_update_connections(node_name, id)
        print("[INFO]: Registering publisher with topic %s on Node %s" % (topic, node_name))
        return True



    def register_subscriber(self, node_name, id, topic, ip, port, protocol):
        '''
        Register a subscriber from a node. This will allow the subscriber to get
        updates on when to connect to publishers and the ports they need to connect to.

        Parameters:
            node_name: The name of the node registering the subscriber.
            id: The unique id of the subscriber.
            topic: The topic name that the subscriber will subscribe to get data from.
            protocol: Either udp or tcp.
        Returns:
            N/A
        '''
        self.node_information[node_name]["subscribers"][id] = {"topic":topic,
                                                                "ip":ip,
                                                                "port":port,
                                                                "protocol":protocol}
        print("[INFO]: Registering subscriber with topic %s on Node %s" % (topic, node_name))
        self.new_subscriber_update_connections(node_name, id)
        return(True)


    def new_subscriber_update_connections(self, node_name, subscriber_id):
        '''
        If a new subscriber of publisher comes onto the network, connect it with its counter
        parts.

        Parameters:
            node_name: The name of the node that has publisher who need to connect to this new subscriber.
            subscriber_id: The id of the subscriber that a publisher of node_name needs to connect to.
        Returns:
            N/A
        '''
        xmlrpc_client_to_subscriber_node = self.xmlrpc_clients_to_nodes[node_name]
        subscriber_topic = self.node_information[node_name]["subscribers"][subscriber_id]["topic"]
        subscriber_protocol =  self.node_information[node_name]["subscribers"][subscriber_id]["protocol"]
        subscriber_ip = self.node_information[node_name]["subscribers"][subscriber_id]["ip"]
        subscriber_port = self.node_information[node_name]["subscribers"][subscriber_id]["port"]
        #Iterate through each nodes publishers, and connect it to the repectable topics
        for nodes in self.node_information.keys():

            for publisher_id in self.node_information[nodes]["publishers"].keys():

                #publisher topics of current node.
                publisher_topic = self.node_information[nodes]["publishers"][publisher_id]["topic"]
                publisher_ip = self.node_information[nodes]["publishers"][publisher_id]["ip"]
                publisher_port = self.node_information[nodes]["publishers"][publisher_id]["port"]
                publisher_protocol = self.node_information[nodes]["publishers"][publisher_id]["protocol"]

                xmlrpc_client_to_publisher_node = self.xmlrpc_clients_to_nodes[nodes]

                #Only connect subscribers to a publisher if they have the same topic name and protocol type.
                if(publisher_topic == subscriber_topic and publisher_protocol == subscriber_protocol):

                    xmlrpc_client_to_publisher_node._update_publisher(publisher_id, subscriber_id, subscriber_ip, subscriber_port)
                    xmlrpc_client_to_subscriber_node._update_subscriber(subscriber_id, publisher_id, publisher_ip, publisher_port)

    def new_publisher_update_connections(self, node_name, publisher_id):
        '''
        If a new publisher comes onto the network, tell the subscriber of the topic
        to connect.

        Parameters:
            node_name:
            publisher_id: The unique publisher id.
        Returns:
            N/A
        '''
        xmlrpc_client_to_publisher_node = self.xmlrpc_clients_to_nodes[node_name]
        publisher_topic = self.node_information[node_name]["publishers"][publisher_id]["topic"]
        publisher_ip = self.node_information[node_name]["publishers"][publisher_id]["ip"]
        publisher_port = self.node_information[node_name]["publishers"][publisher_id]["port"]
        publisher_protocol = self.node_information[node_name]["publishers"][publisher_id]["protocol"]


        for nodes in self.node_information.keys():

            for subscriber_id in self.node_information[nodes]["subscribers"].keys():

                #publisher topics of current node.
                subscriber_topic = self.node_information[nodes]["subscribers"][subscriber_id]["topic"]
                subscriber_protocol = self.node_information[nodes]["subscribers"][subscriber_id]["protocol"]
                subscriber_ip = self.node_information[nodes]["subscribers"][subscriber_id]["ip"]
                subscriber_port = self.node_information[nodes]["subscribers"][subscriber_id]["port"]

                xmlrpc_client_to_subscriber_node = self.xmlrpc_clients_to_nodes[nodes]

                if(publisher_topic == subscriber_topic and publisher_protocol == subscriber_protocol):

                    xmlrpc_client_to_publisher_node._update_publisher(publisher_id, subscriber_id, subscriber_ip, subscriber_port)
                    xmlrpc_client_to_subscriber_node._update_subscriber(subscriber_id, publisher_id, publisher_ip, publisher_port)
                    #xmlrpc_client_to_publisher_node._update_publisher(publisher_id, subscriber_id, subscriber_ip, subscriber_port)

    def run(self):
        '''
        Run the mechoscore server. Also starts the parameter server.

        Parameters:
            N/A
        Returns:
            N/A
        '''
        print("[INFO]: mechoscore started.")
        print("[INFO]: Node Connection Server started at %s:%d" % (self.ip, self.core_port))
        print("[INFO]: Parameter Server started at %s:%d" % (self.ip, self.param_server_port))
        self.param_server_thread = threading.Thread(target=self.param_server.run, daemon=True)

        #Start the xmlrpc server of mechoscore and the parameter server
        self.param_server_thread.start()

        self.xmlrpc_server.serve_forever()

if __name__ == "__main__":

     #Parse arguments to choose ip_  address and Pub/Sub ports
    parser = argparse.ArgumentParser()
    parser.add_argument("--ip", default='127.0.0.1',
            help='''IP address location to run mechoscore for
                  nodes to connect to and the parameter server.
                  Default is 127.0.0.1''',type=str)

    parser.add_argument("--core_port", default=5959,
            help='''The port that mechoscores xmlrpc server is for node registration.''', type=int)

    parser.add_argument("--param_server_port", default=8000,
            help='''The port that the parameter server is running on. Default 8000''', type=int)

    args= parser.parse_args()


    mechoscore_server = Mechoscore(ip=args.ip, core_port=args.core_port, param_server_port=args.param_server_port)
    mechoscore_server.run()
