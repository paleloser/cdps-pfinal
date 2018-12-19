echo "Borrando contenedores..."
lxc delete firewall --force
lxc delete loadbalancer --force
lxc delete webserver0 --force
lxc delete webserver1 --force
lxc delete webserver2 --force
lxc delete storage0 --force
lxc delete storage1 --force
lxc delete storage2 --force
lxc delete database --force

echo "Desconectando interfaces de red"
sudo ifconfig intra-lan0 down
sudo ifconfig intra-lan1 down
sudo ifconfig intra-lan2 down

echo "Borrando bridges"
sudo brctl delbr intra-lan0
sudo brctl delbr intra-lan1
sudo brctl delbr intra-lan2

echo "Desinstalacion completada"