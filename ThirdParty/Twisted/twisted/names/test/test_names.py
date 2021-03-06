# -*- test-case-name: twisted.names.test.test_names -*-
# Copyright (c) Twisted Matrix Laboratories.
# See LICENSE for details.

"""
Test cases for twisted.names.
"""

import socket, operator, copy
from StringIO import StringIO

from twisted.trial import unittest

from twisted.internet import reactor, defer, error
from twisted.internet.task import Clock
from twisted.internet.defer import succeed
from twisted.names import client, server, common, authority, dns
from twisted.python import failure
from twisted.names.dns import Message
from twisted.names.client import Resolver
from twisted.names.secondary import (
    SecondaryAuthorityService, SecondaryAuthority)

from twisted.python.compat import reduce
from twisted.test.proto_helpers import StringTransport, MemoryReactor

def justPayload(results):
    return [r.payload for r in results[0]]

class NoFileAuthority(authority.FileAuthority):
    def __init__(self, soa, records):
        # Yes, skip FileAuthority
        common.ResolverBase.__init__(self)
        self.soa, self.records = soa, records


soa_record = dns.Record_SOA(
                    mname = 'test-domain.com',
                    rname = 'root.test-domain.com',
                    serial = 100,
                    refresh = 1234,
                    minimum = 7654,
                    expire = 19283784,
                    retry = 15,
                    ttl=1
                )

reverse_soa = dns.Record_SOA(
                     mname = '93.84.28.in-addr.arpa',
                     rname = '93.84.28.in-addr.arpa',
                     serial = 120,
                     refresh = 54321,
                     minimum = 382,
                     expire = 11193983,
                     retry = 30,
                     ttl=3
                )

my_soa = dns.Record_SOA(
    mname = 'my-domain.com',
    rname = 'postmaster.test-domain.com',
    serial = 130,
    refresh = 12345,
    minimum = 1,
    expire = 999999,
    retry = 100,
    )

test_domain_com = NoFileAuthority(
    soa = ('test-domain.com', soa_record),
    records = {
        'test-domain.com': [
            soa_record,
            dns.Record_A('127.0.0.1'),
            dns.Record_NS('39.28.189.39'),
            dns.Record_SPF('v=spf1 mx/30 mx:example.org/30 -all'),
            dns.Record_SPF('v=spf1 +mx a:\0colo', '.example.com/28 -all not valid'),
            dns.Record_MX(10, 'host.test-domain.com'),
            dns.Record_HINFO(os='Linux', cpu='A Fast One, Dontcha know'),
            dns.Record_CNAME('canonical.name.com'),
            dns.Record_MB('mailbox.test-domain.com'),
            dns.Record_MG('mail.group.someplace'),
            dns.Record_TXT('A First piece of Text', 'a SecoNd piece'),
            dns.Record_A6(0, 'ABCD::4321', ''),
            dns.Record_A6(12, '0:0069::0', 'some.network.tld'),
            dns.Record_A6(8, '0:5634:1294:AFCB:56AC:48EF:34C3:01FF', 'tra.la.la.net'),
            dns.Record_TXT('Some more text, haha!  Yes.  \0  Still here?'),
            dns.Record_MR('mail.redirect.or.whatever'),
            dns.Record_MINFO(rmailbx='r mail box', emailbx='e mail box'),
            dns.Record_AFSDB(subtype=1, hostname='afsdb.test-domain.com'),
            dns.Record_RP(mbox='whatever.i.dunno', txt='some.more.text'),
            dns.Record_WKS('12.54.78.12', socket.IPPROTO_TCP,
                           '\x12\x01\x16\xfe\xc1\x00\x01'),
            dns.Record_NAPTR(100, 10, "u", "sip+E2U",
                             "!^.*$!sip:information@domain.tld!"),
            dns.Record_AAAA('AF43:5634:1294:AFCB:56AC:48EF:34C3:01FF')],
        'http.tcp.test-domain.com': [
            dns.Record_SRV(257, 16383, 43690, 'some.other.place.fool')
        ],
        'host.test-domain.com': [
            dns.Record_A('123.242.1.5'),
            dns.Record_A('0.255.0.255'),
        ],
        'host-two.test-domain.com': [
#
#  Python bug
#           dns.Record_A('255.255.255.255'),
#
            dns.Record_A('255.255.255.254'),
            dns.Record_A('0.0.0.0')
        ],
        'cname.test-domain.com': [
            dns.Record_CNAME('test-domain.com')
        ],
        'anothertest-domain.com': [
            dns.Record_A('1.2.3.4')],
    }
)

reverse_domain = NoFileAuthority(
    soa = ('93.84.28.in-addr.arpa', reverse_soa),
    records = {
        '123.93.84.28.in-addr.arpa': [
             dns.Record_PTR('test.host-reverse.lookup.com'),
             reverse_soa
        ]
    }
)


my_domain_com = NoFileAuthority(
    soa = ('my-domain.com', my_soa),
    records = {
        'my-domain.com': [
            my_soa,
            dns.Record_A('1.2.3.4', ttl='1S'),
            dns.Record_NS('ns1.domain', ttl='2M'),
            dns.Record_NS('ns2.domain', ttl='3H'),
            dns.Record_SRV(257, 16383, 43690, 'some.other.place.fool', ttl='4D')
            ]
        }
    )


class ServerDNSTestCase(unittest.TestCase):
    """
    Test cases for DNS server and client.
    """

    def setUp(self):
        self.factory = server.DNSServerFactory([
            test_domain_com, reverse_domain, my_domain_com
        ], verbose=2)

        p = dns.DNSDatagramProtocol(self.factory)

        while 1:
            listenerTCP = reactor.listenTCP(0, self.factory, interface="127.0.0.1")
            # It's simpler to do the stop listening with addCleanup,
            # even though we might not end up using this TCP port in
            # the test (if the listenUDP below fails).  Cleaning up
            # this TCP port sooner than "cleanup time" would mean
            # adding more code to keep track of the Deferred returned
            # by stopListening.
            self.addCleanup(listenerTCP.stopListening)
            port = listenerTCP.getHost().port

            try:
                listenerUDP = reactor.listenUDP(port, p, interface="127.0.0.1")
            except error.CannotListenError:
                pass
            else:
                self.addCleanup(listenerUDP.stopListening)
                break

        self.listenerTCP = listenerTCP
        self.listenerUDP = listenerUDP
        self.resolver = client.Resolver(servers=[('127.0.0.1', port)])


    def tearDown(self):
        """
        Clean up any server connections associated with the
        L{DNSServerFactory} created in L{setUp}
        """
        # It'd be great if DNSServerFactory had a method that
        # encapsulated this task.  At least the necessary data is
        # available, though.
        for conn in self.factory.connections[:]:
            conn.transport.loseConnection()


    def namesTest(self, d, r):
        self.response = None
        def setDone(response):
            self.response = response

        def checkResults(ignored):
            if isinstance(self.response, failure.Failure):
                raise self.response
            results = justPayload(self.response)
            assert len(results) == len(r), "%s != %s" % (map(str, results), map(str, r))
            for rec in results:
                assert rec in r, "%s not in %s" % (rec, map(str, r))

        d.addBoth(setDone)
        d.addCallback(checkResults)
        return d

    def testAddressRecord1(self):
        """Test simple DNS 'A' record queries"""
        return self.namesTest(
            self.resolver.lookupAddress('test-domain.com'),
            [dns.Record_A('127.0.0.1', ttl=19283784)]
        )


    def testAddressRecord2(self):
        """Test DNS 'A' record queries with multiple answers"""
        return self.namesTest(
            self.resolver.lookupAddress('host.test-domain.com'),
            [dns.Record_A('123.242.1.5', ttl=19283784), dns.Record_A('0.255.0.255', ttl=19283784)]
        )


    def testAddressRecord3(self):
        """Test DNS 'A' record queries with edge cases"""
        return self.namesTest(
            self.resolver.lookupAddress('host-two.test-domain.com'),
            [dns.Record_A('255.255.255.254', ttl=19283784), dns.Record_A('0.0.0.0', ttl=19283784)]
        )


    def testAuthority(self):
        """Test DNS 'SOA' record queries"""
        return self.namesTest(
            self.resolver.lookupAuthority('test-domain.com'),
            [soa_record]
        )


    def testMailExchangeRecord(self):
        """Test DNS 'MX' record queries"""
        return self.namesTest(
            self.resolver.lookupMailExchange('test-domain.com'),
            [dns.Record_MX(10, 'host.test-domain.com', ttl=19283784)]
        )


    def testNameserver(self):
        """Test DNS 'NS' record queries"""
        return self.namesTest(
            self.resolver.lookupNameservers('test-domain.com'),
            [dns.Record_NS('39.28.189.39', ttl=19283784)]
        )


    def testHINFO(self):
        """Test DNS 'HINFO' record queries"""
        return self.namesTest(
            self.resolver.lookupHostInfo('test-domain.com'),
            [dns.Record_HINFO(os='Linux', cpu='A Fast One, Dontcha know', ttl=19283784)]
        )

    def testPTR(self):
        """Test DNS 'PTR' record queries"""
        return self.namesTest(
            self.resolver.lookupPointer('123.93.84.28.in-addr.arpa'),
            [dns.Record_PTR('test.host-reverse.lookup.com', ttl=11193983)]
        )


    def testCNAME(self):
        """Test DNS 'CNAME' record queries"""
        return self.namesTest(
            self.resolver.lookupCanonicalName('test-domain.com'),
            [dns.Record_CNAME('canonical.name.com', ttl=19283784)]
        )

    def testCNAMEAdditional(self):
        """Test additional processing for CNAME records"""
        return self.namesTest(
        self.resolver.lookupAddress('cname.test-domain.com'),
        [dns.Record_CNAME('test-domain.com', ttl=19283784), dns.Record_A('127.0.0.1', ttl=19283784)]
    )

    def testMB(self):
        """Test DNS 'MB' record queries"""
        return self.namesTest(
            self.resolver.lookupMailBox('test-domain.com'),
            [dns.Record_MB('mailbox.test-domain.com', ttl=19283784)]
        )


    def testMG(self):
        """Test DNS 'MG' record queries"""
        return self.namesTest(
            self.resolver.lookupMailGroup('test-domain.com'),
            [dns.Record_MG('mail.group.someplace', ttl=19283784)]
        )


    def testMR(self):
        """Test DNS 'MR' record queries"""
        return self.namesTest(
            self.resolver.lookupMailRename('test-domain.com'),
            [dns.Record_MR('mail.redirect.or.whatever', ttl=19283784)]
        )


    def testMINFO(self):
        """Test DNS 'MINFO' record queries"""
        return self.namesTest(
            self.resolver.lookupMailboxInfo('test-domain.com'),
            [dns.Record_MINFO(rmailbx='r mail box', emailbx='e mail box', ttl=19283784)]
        )


    def testSRV(self):
        """Test DNS 'SRV' record queries"""
        return self.namesTest(
            self.resolver.lookupService('http.tcp.test-domain.com'),
            [dns.Record_SRV(257, 16383, 43690, 'some.other.place.fool', ttl=19283784)]
        )

    def testAFSDB(self):
        """Test DNS 'AFSDB' record queries"""
        return self.namesTest(
            self.resolver.lookupAFSDatabase('test-domain.com'),
            [dns.Record_AFSDB(subtype=1, hostname='afsdb.test-domain.com', ttl=19283784)]
        )


    def testRP(self):
        """Test DNS 'RP' record queries"""
        return self.namesTest(
            self.resolver.lookupResponsibility('test-domain.com'),
            [dns.Record_RP(mbox='whatever.i.dunno', txt='some.more.text', ttl=19283784)]
        )


    def testTXT(self):
        """Test DNS 'TXT' record queries"""
        return self.namesTest(
            self.resolver.lookupText('test-domain.com'),
            [dns.Record_TXT('A First piece of Text', 'a SecoNd piece', ttl=19283784),
             dns.Record_TXT('Some more text, haha!  Yes.  \0  Still here?', ttl=19283784)]
        )


    def test_spf(self):
        """
        L{DNSServerFactory} can serve I{SPF} resource records.
        """
        return self.namesTest(
            self.resolver.lookupSenderPolicy('test-domain.com'),
            [dns.Record_SPF('v=spf1 mx/30 mx:example.org/30 -all', ttl=19283784),
            dns.Record_SPF('v=spf1 +mx a:\0colo', '.example.com/28 -all not valid', ttl=19283784)]
        )


    def testWKS(self):
        """Test DNS 'WKS' record queries"""
        return self.namesTest(
            self.resolver.lookupWellKnownServices('test-domain.com'),
            [dns.Record_WKS('12.54.78.12', socket.IPPROTO_TCP, '\x12\x01\x16\xfe\xc1\x00\x01', ttl=19283784)]
        )


    def testSomeRecordsWithTTLs(self):
        result_soa = copy.copy(my_soa)
        result_soa.ttl = my_soa.expire
        return self.namesTest(
            self.resolver.lookupAllRecords('my-domain.com'),
            [result_soa,
             dns.Record_A('1.2.3.4', ttl='1S'),
             dns.Record_NS('ns1.domain', ttl='2M'),
             dns.Record_NS('ns2.domain', ttl='3H'),
             dns.Record_SRV(257, 16383, 43690, 'some.other.place.fool', ttl='4D')]
            )


    def testAAAA(self):
        """Test DNS 'AAAA' record queries (IPv6)"""
        return self.namesTest(
            self.resolver.lookupIPV6Address('test-domain.com'),
            [dns.Record_AAAA('AF43:5634:1294:AFCB:56AC:48EF:34C3:01FF', ttl=19283784)]
        )

    def testA6(self):
        """Test DNS 'A6' record queries (IPv6)"""
        return self.namesTest(
            self.resolver.lookupAddress6('test-domain.com'),
            [dns.Record_A6(0, 'ABCD::4321', '', ttl=19283784),
             dns.Record_A6(12, '0:0069::0', 'some.network.tld', ttl=19283784),
             dns.Record_A6(8, '0:5634:1294:AFCB:56AC:48EF:34C3:01FF', 'tra.la.la.net', ttl=19283784)]
         )


    def test_zoneTransfer(self):
        """
        Test DNS 'AXFR' queries (Zone transfer)
        """
        default_ttl = soa_record.expire
        results = [copy.copy(r) for r in reduce(operator.add, test_domain_com.records.values())]
        for r in results:
            if r.ttl is None:
                r.ttl = default_ttl
        return self.namesTest(
            self.resolver.lookupZone('test-domain.com').addCallback(lambda r: (r[0][:-1],)),
            results
        )


    def testSimilarZonesDontInterfere(self):
        """Tests that unrelated zones don't mess with each other."""
        return self.namesTest(
            self.resolver.lookupAddress("anothertest-domain.com"),
            [dns.Record_A('1.2.3.4', ttl=19283784)]
        )


    def test_NAPTR(self):
        """
        Test DNS 'NAPTR' record queries.
        """
        return self.namesTest(
            self.resolver.lookupNamingAuthorityPointer('test-domain.com'),
            [dns.Record_NAPTR(100, 10, "u", "sip+E2U",
                              "!^.*$!sip:information@domain.tld!",
                              ttl=19283784)])



class DNSServerFactoryTests(unittest.TestCase):
    """
    Tests for L{server.DNSServerFactory}.
    """
    def _messageReceivedTest(self, methodName, message):
        """
        Assert that the named method is called with the given message when
        it is passed to L{DNSServerFactory.messageReceived}.
        """
        # Make it appear to have some queries so that
        # DNSServerFactory.allowQuery allows it.
        message.queries = [None]

        receivedMessages = []
        def fakeHandler(message, protocol, address):
            receivedMessages.append((message, protocol, address))

        class FakeProtocol(object):
            def writeMessage(self, message):
                pass

        protocol = FakeProtocol()
        factory = server.DNSServerFactory(None)
        setattr(factory, methodName, fakeHandler)
        factory.messageReceived(message, protocol)
        self.assertEqual(receivedMessages, [(message, protocol, None)])


    def test_notifyMessageReceived(self):
        """
        L{DNSServerFactory.messageReceived} passes messages with an opcode
        of C{OP_NOTIFY} on to L{DNSServerFactory.handleNotify}.
        """
        # RFC 1996, section 4.5
        opCode = 4
        self._messageReceivedTest('handleNotify', Message(opCode=opCode))


    def test_updateMessageReceived(self):
        """
        L{DNSServerFactory.messageReceived} passes messages with an opcode
        of C{OP_UPDATE} on to L{DNSServerFactory.handleOther}.

        This may change if the implementation ever covers update messages.
        """
        # RFC 2136, section 1.3
        opCode = 5
        self._messageReceivedTest('handleOther', Message(opCode=opCode))


    def test_connectionTracking(self):
        """
        The C{connectionMade} and C{connectionLost} methods of
        L{DNSServerFactory} cooperate to keep track of all
        L{DNSProtocol} objects created by a factory which are
        connected.
        """
        protoA, protoB = object(), object()
        factory = server.DNSServerFactory()
        factory.connectionMade(protoA)
        self.assertEqual(factory.connections, [protoA])
        factory.connectionMade(protoB)
        self.assertEqual(factory.connections, [protoA, protoB])
        factory.connectionLost(protoA)
        self.assertEqual(factory.connections, [protoB])
        factory.connectionLost(protoB)
        self.assertEqual(factory.connections, [])


class HelperTestCase(unittest.TestCase):
    def testSerialGenerator(self):
        f = self.mktemp()
        a = authority.getSerial(f)
        for i in range(20):
            b = authority.getSerial(f)
            self.failUnless(a < b)
            a = b


class AXFRTest(unittest.TestCase):
    def setUp(self):
        self.results = None
        self.d = defer.Deferred()
        self.d.addCallback(self._gotResults)
        self.controller = client.AXFRController('fooby.com', self.d)

        self.soa = dns.RRHeader(name='fooby.com', type=dns.SOA, cls=dns.IN, ttl=86400, auth=False,
                                payload=dns.Record_SOA(mname='fooby.com',
                                                       rname='hooj.fooby.com',
                                                       serial=100,
                                                       refresh=200,
                                                       retry=300,
                                                       expire=400,
                                                       minimum=500,
                                                       ttl=600))

        self.records = [
            self.soa,
            dns.RRHeader(name='fooby.com', type=dns.NS, cls=dns.IN, ttl=700, auth=False,
                         payload=dns.Record_NS(name='ns.twistedmatrix.com', ttl=700)),

            dns.RRHeader(name='fooby.com', type=dns.MX, cls=dns.IN, ttl=700, auth=False,
                         payload=dns.Record_MX(preference=10, exchange='mail.mv3d.com', ttl=700)),

            dns.RRHeader(name='fooby.com', type=dns.A, cls=dns.IN, ttl=700, auth=False,
                         payload=dns.Record_A(address='64.123.27.105', ttl=700)),
            self.soa
            ]

    def _makeMessage(self):
        # hooray they all have the same message format
        return dns.Message(id=999, answer=1, opCode=0, recDes=0, recAv=1, auth=1, rCode=0, trunc=0, maxSize=0)

    def testBindAndTNamesStyle(self):
        # Bind style = One big single message
        m = self._makeMessage()
        m.queries = [dns.Query('fooby.com', dns.AXFR, dns.IN)]
        m.answers = self.records
        self.controller.messageReceived(m, None)
        self.assertEqual(self.results, self.records)

    def _gotResults(self, result):
        self.results = result

    def testDJBStyle(self):
        # DJB style = message per record
        records = self.records[:]
        while records:
            m = self._makeMessage()
            m.queries = [] # DJB *doesn't* specify any queries.. hmm..
            m.answers = [records.pop(0)]
            self.controller.messageReceived(m, None)
        self.assertEqual(self.results, self.records)



class ResolvConfHandling(unittest.TestCase):
    def testMissing(self):
        resolvConf = self.mktemp()
        r = client.Resolver(resolv=resolvConf)
        self.assertEqual(r.dynServers, [('127.0.0.1', 53)])
        r._parseCall.cancel()

    def testEmpty(self):
        resolvConf = self.mktemp()
        fObj = file(resolvConf, 'w')
        fObj.close()
        r = client.Resolver(resolv=resolvConf)
        self.assertEqual(r.dynServers, [('127.0.0.1', 53)])
        r._parseCall.cancel()



class AuthorityTests(unittest.TestCase):
    """
    Tests for the basic response record selection code in L{FileAuthority}
    (independent of its fileness).
    """
    def test_recordMissing(self):
        """
        If a L{FileAuthority} has a zone which includes an I{NS} record for a
        particular name and that authority is asked for another record for the
        same name which does not exist, the I{NS} record is not included in the
        authority section of the response.
        """
        authority = NoFileAuthority(
            soa=(str(soa_record.mname), soa_record),
            records={
                str(soa_record.mname): [
                    soa_record,
                    dns.Record_NS('1.2.3.4'),
                    ]})
        d = authority.lookupAddress(str(soa_record.mname))
        result = []
        d.addCallback(result.append)
        answer, authority, additional = result[0]
        self.assertEqual(answer, [])
        self.assertEqual(
            authority, [
                dns.RRHeader(
                    str(soa_record.mname), soa_record.TYPE,
                    ttl=soa_record.expire, payload=soa_record,
                    auth=True)])
        self.assertEqual(additional, [])


    def _referralTest(self, method):
        """
        Create an authority and make a request against it.  Then verify that the
        result is a referral, including no records in the answers or additional
        sections, but with an I{NS} record in the authority section.
        """
        subdomain = 'example.' + str(soa_record.mname)
        nameserver = dns.Record_NS('1.2.3.4')
        authority = NoFileAuthority(
            soa=(str(soa_record.mname), soa_record),
            records={
                subdomain: [
                    nameserver,
                    ]})
        d = getattr(authority, method)(subdomain)
        result = []
        d.addCallback(result.append)
        answer, authority, additional = result[0]
        self.assertEqual(answer, [])
        self.assertEqual(
            authority, [dns.RRHeader(
                    subdomain, dns.NS, ttl=soa_record.expire,
                    payload=nameserver, auth=False)])
        self.assertEqual(additional, [])


    def test_referral(self):
        """
        When an I{NS} record is found for a child zone, it is included in the
        authority section of the response.  It is marked as non-authoritative if
        the authority is not also authoritative for the child zone (RFC 2181,
        section 6.1).
        """
        self._referralTest('lookupAddress')


    def test_allRecordsReferral(self):
        """
        A referral is also generated for a request of type C{ALL_RECORDS}.
        """
        self._referralTest('lookupAllRecords')



class NoInitialResponseTestCase(unittest.TestCase):

    def test_no_answer(self):
        """
        If a request returns a L{dns.NS} response, but we can't connect to the
        given server, the request fails with the error returned at connection.
        """

        def query(self, *args):
            # Pop from the message list, so that it blows up if more queries
            # are run than expected.
            return succeed(messages.pop(0))

        def queryProtocol(self, *args, **kwargs):
            return defer.fail(socket.gaierror("Couldn't connect"))

        resolver = Resolver(servers=[('0.0.0.0', 0)])
        resolver._query = query
        messages = []
        # Let's patch dns.DNSDatagramProtocol.query, as there is no easy way to
        # customize it.
        self.patch(dns.DNSDatagramProtocol, "query", queryProtocol)

        records = [
            dns.RRHeader(name='fooba.com', type=dns.NS, cls=dns.IN, ttl=700,
                         auth=False,
                         payload=dns.Record_NS(name='ns.twistedmatrix.com',
                         ttl=700))]
        m = dns.Message(id=999, answer=1, opCode=0, recDes=0, recAv=1, auth=1,
                        rCode=0, trunc=0, maxSize=0)
        m.answers = records
        messages.append(m)
        return self.assertFailure(
            resolver.getHostByName("fooby.com"), socket.gaierror)



class SecondaryAuthorityServiceTests(unittest.TestCase):
    """
    Tests for L{SecondaryAuthorityService}, a service which keeps one or more
    authorities up to date by doing zone transfers from a master.
    """

    def test_constructAuthorityFromHost(self):
        """
        L{SecondaryAuthorityService} can be constructed with a C{str} giving a
        master server address and several domains, causing the creation of a
        secondary authority for each domain and that master server address and
        the default DNS port.
        """
        primary = '192.168.1.2'
        service = SecondaryAuthorityService(
            primary, ['example.com', 'example.org'])
        self.assertEqual(service.primary, primary)
        self.assertEqual(service._port, 53)

        self.assertEqual(service.domains[0].primary, primary)
        self.assertEqual(service.domains[0]._port, 53)
        self.assertEqual(service.domains[0].domain, 'example.com')

        self.assertEqual(service.domains[1].primary, primary)
        self.assertEqual(service.domains[1]._port, 53)
        self.assertEqual(service.domains[1].domain, 'example.org')


    def test_constructAuthorityFromHostAndPort(self):
        """
        L{SecondaryAuthorityService.fromServerAddressAndDomains} constructs a
        new L{SecondaryAuthorityService} from a C{str} giving a master server
        address and DNS port and several domains, causing the creation of a secondary
        authority for each domain and that master server address and the given
        DNS port.
        """
        primary = '192.168.1.3'
        port = 5335
        service = SecondaryAuthorityService.fromServerAddressAndDomains(
            (primary, port), ['example.net', 'example.edu'])
        self.assertEqual(service.primary, primary)
        self.assertEqual(service._port, 5335)

        self.assertEqual(service.domains[0].primary, primary)
        self.assertEqual(service.domains[0]._port, port)
        self.assertEqual(service.domains[0].domain, 'example.net')

        self.assertEqual(service.domains[1].primary, primary)
        self.assertEqual(service.domains[1]._port, port)
        self.assertEqual(service.domains[1].domain, 'example.edu')



class SecondaryAuthorityTests(unittest.TestCase):
    """
    L{twisted.names.secondary.SecondaryAuthority} correctly constructs objects
    with a specified IP address and optionally specified DNS port.
    """

    def test_defaultPort(self):
        """
        When constructed using L{SecondaryAuthority.__init__}, the default port
        of 53 is used.
        """
        secondary = SecondaryAuthority('192.168.1.1', 'inside.com')
        self.assertEqual(secondary.primary, '192.168.1.1')
        self.assertEqual(secondary._port, 53)
        self.assertEqual(secondary.domain, 'inside.com')


    def test_explicitPort(self):
        """
        When constructed using L{SecondaryAuthority.fromServerAddressAndDomain},
        the specified port is used.
        """
        secondary = SecondaryAuthority.fromServerAddressAndDomain(
            ('192.168.1.1', 5353), 'inside.com')
        self.assertEqual(secondary.primary, '192.168.1.1')
        self.assertEqual(secondary._port, 5353)
        self.assertEqual(secondary.domain, 'inside.com')


    def test_transfer(self):
        """
        An attempt is made to transfer the zone for the domain the
        L{SecondaryAuthority} was constructed with from the server address it
        was constructed with when L{SecondaryAuthority.transfer} is called.
        """
        class ClockMemoryReactor(Clock, MemoryReactor):
            def __init__(self):
                Clock.__init__(self)
                MemoryReactor.__init__(self)

        secondary = SecondaryAuthority.fromServerAddressAndDomain(
            ('192.168.1.2', 1234), 'example.com')
        secondary._reactor = reactor = ClockMemoryReactor()

        secondary.transfer()

        # Verify a connection attempt to the server address above
        host, port, factory, timeout, bindAddress = reactor.tcpClients.pop(0)
        self.assertEqual(host, '192.168.1.2')
        self.assertEqual(port, 1234)

        # See if a zone transfer query is issued.
        proto = factory.buildProtocol((host, port))
        transport = StringTransport()
        proto.makeConnection(transport)

        msg = Message()
        # DNSProtocol.writeMessage length encodes the message by prepending a
        # 2 byte message length to the buffered value.
        msg.decode(StringIO(transport.value()[2:]))

        self.assertEqual(
            [dns.Query('example.com', dns.AXFR, dns.IN)], msg.queries)
