from zeroconf import ServiceBrowser, Zeroconf, ServiceInfo
import six

_LOOKUP_INTERVAL = 500


class Service(object):
    def __init__(self, type_=''):
        self.type = type_
        self.domain = 'local'
        self.base_type = 'machinekit'
        self.protocol = 'tcp'
        self.name = ''
        self.uri = ''
        self.uuid = ''
        self.version = 0
        self._ready = False

        self.service_infos = []

        # callback
        self.on_ready_changed = []

    @property
    def ready(self):
        return self._ready

    @ready.setter
    def ready(self, value):
        if value != self._ready:
            self._ready = value
            for cb in self.on_ready_changed:
                cb(value)

    @property
    def typestring(self):
        return '_%s._%s.%s.' % (self.base_type, self.protocol, self.domain)

    def matches_service_info(self, info):
        return self.type == info.properties.get(b'service', b'').decode() \
            and self.typestring in info.type

    def __eq__(self, other):
        if isinstance(other, ServiceInfo):
            return self.name == other.name
        return False

    def add_service_info(self, info):
        self.service_infos.append(info)
        self._update()

    def remove_service_info(self, info):
        for info in self.service_infos:
            if self == info:
                self.service_infos.remove(info)
                break
        self._update()

    def clear_service_infos(self):
        self.service_infos = []
        self._update()

    def _update(self):
        if len(self.service_infos) > 0:
            info = self.service_infos[0]
            self._set_all_values_from_service_info(info)
            self.ready = True
        else:
            self.ready = False
            self._init_all_values()

    def _set_all_values_from_service_info(self, info):
        self.name = info.name
        self.uri = info.properties.get(b'dsn', b'').decode()
        self.uuid = info.properties.get(b'uuid', b'').decode()
        self.version = info.properties.get(b'version', b'')

    def _init_all_values(self):
        self.name = ''
        self.uri = ''
        self.uuid = ''
        self.version = 0


class ServiceDiscoveryFilter(object):
    def __init__(self, name='', txt_records={}):
        self.name = name
        self.txt_records = txt_records

    def matches_service_info(self, info):
        if not isinstance(info, ServiceInfo):
            raise TypeError('must pass a ServiceInfo object')
        match = True
        if self.name not in info.name:
            match = False
        for name, value in six.iteritems(self.txt_records):
            if not info.properties[name] == value:
                match = False
                break
        return match


class ServiceDiscovery(object):
    def __init__(self, service_type='machinekit', filter_=ServiceDiscoveryFilter(),
                 nameservers=[], lookup_interval=_LOOKUP_INTERVAL):
        """ Initialize the multicast or unicast DNS-SD service discovery instance.
        @param service_type DNS-SD type use for discovery, does not need to be changed for Machinekit.
        @param filter Optional filter can be used to look for specific instances.
        @param nameservers Pass one or more nameserver addresses to enabled unicast service discovery.
        @param lookup_interval How often the SD should send out service queries.
        """
        self.service_type = service_type
        self.filter = filter_
        self.nameservers = nameservers
        self.lookup_interval = lookup_interval

        self.is_ready = False
        self.services = []
        self._browsers = None
        self._zeroconfs = None

    def _start_discovery(self):
        self._zeroconfs = []
        self._browsers = []
        if any(self.nameservers):
            self._start_unicast_discovery()
        else:
            self._start_multicast_discovery()

    def _start_multicast_discovery(self):
        type_string = '_%s._tcp.local.' % self.service_type
        zeroconf = Zeroconf()
        self._zeroconfs.append(zeroconf)
        self._browsers.append(ServiceBrowser(zeroconf, type_string, self, delay=self.lookup_interval))

    def _start_unicast_discovery(self):
        for service in self.services:
            type_string = '_%s._sub._%s._tcp.local.' % (service.type, self.service_type)
            zeroconf = Zeroconf(unicast=True)
            self._zeroconfs.append(zeroconf)
            for nameserver in self.nameservers:
                self._browsers.append(ServiceBrowser(zeroconf, type_string, self,
                                                     addr=nameserver, delay=self.lookup_interval))

    def _stop_discovery(self):
        for zeroconf in self._zeroconfs:
            zeroconf.close()
        del self._zeroconfs[:]
        del self._browsers[:]
        for service in self.services:
            service.clear_service_infos()

    def remove_service(self, zeroconf, type_, name):
        info = zeroconf.get_service_info(type_, name)
        if info is None:
            return
        for service in self.services:
            if self.filter.matches_service_info(info) and service.matches_service_info(info):
                service.remove_service_info(info)

    def add_service(self, zeroconf, type_, name):
        info = zeroconf.get_service_info(type_, name)
        if info is None:
            return
        for service in self.services:
            if self.filter.matches_service_info(info) and service.matches_service_info(info):
                service.add_service_info(info)

    def _verify_item_and_run(self, item, cmd):
        if isinstance(item, ServiceContainer):
            for service in item.services:
                cmd(service)
        elif isinstance(item, Service):
            cmd(item)
        else:
            raise TypeError('passed unregisterable item')

    def register(self, item):
        if self.is_ready:
            raise RuntimeError('cannot register service when service discovery is already running')
        self._verify_item_and_run(item, self.services.append)

    def unregister(self, item):
        if self.is_ready:
            raise RuntimeError('cannot unregister service when service discovery is already running')
        self._verify_item_and_run(item, self.services.remove)

    def start(self):
        if not self._browsers:
            self.is_ready = True
            self._start_discovery()

    def stop(self):
        if self._browsers:
            self.is_ready = False
            self._stop_discovery()


class ServiceContainer(object):
    def __init__(self):
        self._services = []
        self._services_ready = False

        self.on_services_ready_changed = []

    @property
    def services(self):
        return self._services

    def add_service(self, service):
        if not isinstance(service, Service):
            raise TypeError('only Service is supported')
        self._services.append(service)
        service.on_ready_changed.append(self._update_services_ready)

    def remove_service(self, service):
        if not isinstance(service, Service):
            raise TypeError('only Service is supported')
        self._services.remove(service)
        service.on_ready_changed.remove(self._update_services_ready)

    @property
    def services_ready(self):
        return self._services_ready

    @services_ready.setter
    def services_ready(self, value):
        if value is not self._services_ready:
            self._services_ready = value
            for cb in self.on_services_ready_changed:
                cb(value)

    def _update_services_ready(self, _):
        ready = True
        for service in self._services:
            if not service.ready:
                ready = False
                break
        self.services_ready = ready
