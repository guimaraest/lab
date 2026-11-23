# lab

repo for compose files

## homelab structure

the homelab structure is declarated in docker and config files that encapsulate its behaviour to a single repo

~/lab folder in the server
https://github.com/guimaraest/lab

some files are left uncommited:

- volumes
- .env
- service data and config

## networking

both the server and client have this setup:

- ufw and ufw-docker enabled
- ufw set to deny incoming
- fail2ban on ssh
- unattended-upgrades & apt-listchanges enabled

server has a single port open to lan for ssh (tcp), it is not 22
the client has an ssh key into server, client has ssh configured but disabled (only one way control)

> client --> server

the lab will use a cloudflare tunnel to expose its services like nextcloud to the domain

minecraft uses its own tunneling service, playit.gg

## lab cli

custom python cli for managing homelab, the entrypoint is cli.py.

```text
lab up [BEAKER] [--build] [--logs] [-d | --detach] [--tolerance low|high]
lab run [BEAKER] [--build] [--logs] [-d | --detach] [--tolerance low|high]
lab restart [BEAKER] [--build] [--logs] [-d | --detach] [--tolerance low|high]
lab down [BEAKER]
lab test [BEAKER]

lab beaker <BEAKER> {status|up|down|restart|listen|attach|test|flag}
lab beaker <BEAKER> up [--build] [--logs] [-d | --detach] [--tolerance low|high]
lab beaker <BEAKER> restart [--build] [--logs] [-d | --detach] [--tolerance low|high]
lab beaker <BEAKER> attach [SERVICE]
lab beaker <BEAKER> flag autostart {true|false}
```