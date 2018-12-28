import json
import sys
import os
import time
import yaml
from pybrctl import BridgeController

###################
# Minor functions #
###################

# In replication cases, only the first address is given, so we have to craft the addr of the replicas
def parseAddr(addr, i):
  split1=addr.split('/')
  split2=[]
  for j in range(0, len(split1)):
    split2.append(split1[j].split('.'))
  # we get something like [[AA, AA, AA, AA], [MM]]
  # we want to set pos [0][3]
  split2[0][3]=int(split2[0][3])+i
  res=('%s.%s.%s.%s/%s' % (split2[0][0], split2[0][1], split2[0][2], split2[0][3], split2[1][0]))
  return res

# kind of a dhcp implementation
def findAvailableAddr(addr, network, start):
  split1=addr.split('/')
  split2=[]
  for j in range(0, len(split1)):
    split2.append(split1[j].split('.'))
  # we get something like [[AA, AA, AA, AA], [MM]]
  # we want to set pos [0][3]
  os.system('lxc network show %s > .tmp.yaml' % (network))
  with open('.tmp.yaml') as infile:
    i=0
    if start:
      i=start
    loaded=yaml.load(infile)
    if loaded:
      if 'used_by' in loaded:
        i=len(loaded['used_by'])
    split2[0][3]=i+1
    addr=('%s.%s.%s.%s/%s' % (split2[0][0], split2[0][1], split2[0][2], split2[0][3], split2[1][0]))
  infile.close()
  os.remove('.tmp.yaml')
  return addr

##############################################################################
# Core functions in the order they are called along the installation process #
##############################################################################

# Launches the container
def launchContainer(node, cfg):
  os.system('lxc launch %s %s 1>/dev/null' % (cfg['image'], node))
  time.sleep(5)

# Execs update/upgrade in the container
def updateContainer(node, cfg):
  print('[%s]..Se actualizan los paquetes' % (node))
  os.system('lxc exec %s -- bash -c "apt-get update 1>/dev/null"' % (node))
  os.system('lxc exec %s -- bash -c "apt-get upgrade 1>/dev/null"' % (node))

# Gives privileges to the container (it is needed for the NAS servers)
def setPrivileges(node):
  print('[%s]..Se le dan privilegios al contenedor' % (node))
  os.system('lxc config set %s security.privileged true' % (node))

# Installs all the pgms needed on the container specified by 'dependencies: []'
def installDependencies(node, cfg):
  print('[%s]..Se instalan las dependencias' % (node))
  for dep in cfg['dependencies']:
    print('[%s]...Se instala %s' % (node, dep))
    os.system('lxc exec %s -- bash -c "apt-get install -y %s 1>/dev/null"' % (node, dep))
  print('[%s]..Dependencias instaladas' % (node))

# Sets the environment variables defined by 'env: {}'
def setEnv(node, cfg):
  print('[%s]..Se configuran las variables de entorno' % (node))
  for var in cfg['env']:
    print('[%s]...Se anade: %s=%s' % (node, var, cfg['env'][var]))
    os.system('lxc exec %s -- bash -c \"export %s=%s\"' % (node, var, cfg['env'][var]))
    os.system('lxc exec %s -- bash -c \"echo \'export %s=%s\' >> /root/.bashrc\"' % (node, var, cfg['env'][var]))

# Runs the commands in the container specified in 'run: []'
def run(node, cfg):
  print('[%s]..Se ejecuta la pila de run definidos' % (node))
  for script in cfg['run']:
    print('[%s]...Se ejecuta: %s' % (node, script))
    os.system('lxc exec %s -- bash -c "%s"' % (node, script))

# Generates a script which will be executed on-boot in the container. It contains the commands specified in 'cmd: []'
def cmd(node, cfg):
  print('[%s]..Se genera el script a correr on-boot' % (node))
  bootfile=open('./scripts/lxc-on-boot.sh', 'r+')
  if os.path.exists('./scripts/lxc-py-%s-on-boot.sh' % (node)):
    os.remove('./scripts/lxc-py-%s-on-boot.sh' % (node))
  outfile=open('./scripts/lxc-py-%s-on-boot.sh' % (node), 'w+')
  for line in bootfile:
    if 'start)' in line:
      outfile.write(line)
      for script in cfg['cmd']:
        print('[%s]...Se anade: %s' % (node, script))
        outfile.write('%s\n' % (script))
    else:
      outfile.write(line)
  bootfile.close()
  outfile.close()
  print('[%s]...Se sube el script a %s/etc/init.d/' % (node, node))
  os.system('lxc file push scripts/lxc-py-%s-on-boot.sh %s/etc/init.d/lxc-%s-on-boot.sh' % (node, node, node))
  os.system('lxc exec %s -- bash -c "chmod 755 /etc/init.d/lxc-%s-on-boot.sh"' % (node, node))
  os.system('lxc exec %s -- bash -c "chown root /etc/init.d/lxc-%s-on-boot.sh"' % (node, node))
  os.system('lxc exec %s -- bash -c "chgrp root /etc/init.d/lxc-%s-on-boot.sh"' % (node, node))
  os.system('lxc exec %s -- bash -c "sudo update-rc.d lxc-%s-on-boot.sh defaults"' % (node, node))

# Se encarga de la configuracion de nagios en el cliente
def setupNagios(cfg, node):
  print('[%s]..Se configura nagios' % (node))
  print('[%s]...Se configura nagios en cliente' % (node))
  # instala nagios
  os.system('lxc exec %s -- bash -c "sudo apt-get install -y nagios-nrpe-server nagios-plugins 1>/dev/null"' % (node))
  os.system('lxc exec %s -- bash -c "sudo sed -i /etc/nagios/nrpe.cfg -e \'s/allowed_hosts.*/allowed_hosts=0.0.0.0/\' -e \'s/utf8mb4/utf8/\'"' % (node))
  os.system('lxc exec %s -- bash -c "sudo /etc/init.d/nagios-nrpe-server restart 1>/dev/null"' % (node))
  # configura un dhcp/estatico de direccion ip sobre la red intra-mgmt (la red del nagios)
  address=findAvailableAddr("10.2.0.1/24", "intra-mgmt", 1)
  iname="eth"+str(len(cfg['interfaces']))
  cfg['interfaces'].append({"name": iname, "network": "intra-mgmt", "address": address})
  # configura los parametros del servidor nagios
  print('[%s]...Se configura nagios en servidor' % (node))
  os.system('lxc exec nagios1 -- bash -c "echo \'define host {\' >> /usr/local/nagios/etc/servers/clients.cfg"')
  os.system('lxc exec nagios1 -- bash -c "echo \'\tuse\tlinux-server\' >> /usr/local/nagios/etc/servers/clients.cfg"')
  os.system('lxc exec nagios1 -- bash -c "echo \'\thost_name\t%s\' >> /usr/local/nagios/etc/servers/clients.cfg"' % (node))
  os.system('lxc exec nagios1 -- bash -c "echo \'\talias\t%s\' >> /usr/local/nagios/etc/servers/clients.cfg"' % (node))
  os.system('lxc exec nagios1 -- bash -c "echo \'\taddress\t%s\' >> /usr/local/nagios/etc/servers/clients.cfg"' % (address))
  os.system('lxc exec nagios1 -- bash -c "echo \'}\' >> /usr/local/nagios/etc/servers/clients.cfg"')
  os.system('lxc exec nagios1 -- bash -c "systemctl restart nagios"')
  return cfg

# Configures the networking in the host: creates necessary bridges
def configHostNetwork(node, cfg):
  print('[%s]..Se configuran las redes necesarias en host' % (node))
  for interface in cfg['interfaces']:
    if interface['network'] != 'default':
      try:
        brctl.getbr(interface['network'])
        print('[%s]...Red %s ya existe, no se hace nada' % (node, interface['network']))
      except Exception:
        print('[%s]...Red %s no existe, se crea el bridge' % (node, interface['network']))
        brctl.addbr(interface['network'])

# Sets defult network.manager to ifupdown (/etc/network/interfaces)
def configNetplan(node, cfg):
  if ('18' in cfg['image']) or ('bionic' in cfg['image']):
    print('[******] Imagen detectada como ubuntu:18.04. Instalamos ifupdown.')
    os.system('lxc exec %s -- bash -c "apt-get install -y ifupdown 1>/dev/null"' % (node))
    os.system('lxc exec %s -- bash -c "apt-get purge -y netplan.io 1>/dev/null"' % (node))

# Configures the networking in the container: attaches bridges to container for network isolation
def configContainerNetwork(node, cfg):
  print('[%s]..Se configuran las interfaces de red' % (node))
  print('[%s]..Se para el contenedor' % (node))
  os.system('lxc stop %s 1>/dev/null' % (node))
  for interface in cfg['interfaces']:
    if interface['network'] == 'default':
      continue
    else:
      print('[%s]...Se anade la red %s a la interfaz %s' % (node, interface['network'], interface['name']))
      os.system('lxc network attach %s %s %s' % (interface['network'], node, interface['name']))
  print('[%s]..Se inicia el contenedor' % (node))
  os.system('lxc start %s 1>/dev/null' % (node))

# Configures the internal networking in the container (/etc/network/interfaces script)
def createNetplan(node, cfg, i):
  print('[%s]..Se crea el plan de red' % (node))
  with open('interfaces', 'w') as outfile:
    outfile.write('auto lo\n')
    outfile.write('iface lo inet loopback\n')
    outfile.write('\n')
    for interface in cfg['interfaces']:
      print('[%s]...Se configura %s' % (node, interface['name']))
      if interface['network'] == 'default':
        outfile.write('auto %s\n' % (interface['name']))
        outfile.write('iface %s inet dhcp\n' % (interface['name']))
        outfile.write('\n')
      else:
        outfile.write('auto %s\n' % (interface['name']))
        outfile.write('iface %s inet static\n' % (interface['name']))
        for attribute, value in interface.iteritems():
          if 'name' in attribute or 'network' in attribute:
            continue
          if 'address' in attribute:
            value=parseAddr(value, i)
          outfile.write('        %s %s' % (attribute, value))
        outfile.write('\n')
  outfile.close()

# Pushes the generated network script to the containet and loads it
def applyNetplan(node, cfg):
  print('[%s]..Se aplica el plan de red' % (node))
  os.system('lxc file push ./interfaces %s/etc/network/' % (node))
  os.system('lxc exec %s -- bash -c "sudo service network-manager restart" 1>/dev/null' % (node))
  if 'forwarding' in cfg:
    if cfg['forwarding']:
      print('[%s]...Se habilita redireccionamiento IP' % (node))
      os.system('lxc exec %s -- bash -c \"echo \'net.ipv4.ip_forward = 1\' >> /etc/sysctl.conf\"' % (node))

# Runs literal scripts ON HOST defined by 'scripts: []'
def runScripts(cfg):
  print('[******]..Se ejecuta la pila de scripts literales definidos')
  for script in cfg['scripts']:
    print('[******]...Se ejecuta: %s' % (script))
    os.system('%s' % (script))

# Creates a single container defined by its configuration (cfg) and its id (i)
def createSingleContainer(cfg, i):
  # node will be the variable with the container name along the process
  node="%s%s" % (cfg['name'], i+1)
  print('[%s].Se crea el contenedor' % (node))
  launchContainer(node, cfg)
  print('[%s].Se configura el contenedor' % (node))
  updateContainer(node, cfg)
  if 'privileged' in cfg:
    if cfg['privileged']:
      setPrivileges(node)
  if 'dependencies' in cfg:
    installDependencies(node, cfg)
  # environment variables always before comands
  if 'env' in cfg:
    setEnv(node, cfg)
  # run-once commands
  if 'run' in cfg:
    run(node, cfg)
  # run-on-boot commands
  if 'cmd' in cfg:
    cmd(node, cfg)
  # run nagios-client setupo
  if 'nagios' in cfg:
    if cfg['nagios']:
      # check if mgmt interface is already registered!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
      cfg = setupNagios(cfg, node)
  # networking stuff should be applied at last instance to avoid isolation problems
  if 'interfaces' in cfg:
    configHostNetwork(node, cfg)
    configNetplan(node, cfg)
    configContainerNetwork(node, cfg)
    createNetplan(node, cfg, i)
    applyNetplan(node, cfg)

# Just calls createSingleContainer for each replica, passing its id
def createReplicatedContainer(cfg, replicas):
  for i in range(0, replicas):
    createSingleContainer(cfg, i)

##################################
# First function executed (main) #
##################################

def createContainer(cfg):
  # if replication exists and is > 0 then create replicated container
  if 'replication' in cfg:
    if cfg['replication'] > 0:
      replicas=cfg['replication']
      createReplicatedContainer(cfg, replicas)
    else:
      createSingleContainer(cfg, 0)
  else:
    createSingleContainer(cfg, 0)
  # this is only executed once, wether if replication is enabled or not
  if 'scripts' in cfg:
    # literal commands executed ON HOST
    runScripts(cfg)
  # remember, this was set on createContainer, we have to undo it
  if 'privileged' in cfg:
    if cfg['privileged']:
      print('[******] NOTE that %s containers were created with privileges!!!! It is your responsability to turn each container privileges off!!!!' % (cfg['name']))

#########
# START #
#########

filename=sys.argv[1]
fopen=open(filename, 'r')
cfg=json.load(fopen)
brctl = BridgeController()

createContainer(cfg)