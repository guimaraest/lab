# CEA Studio

A React + TypeScript interface for the NASA Chemical Equilibrium with Applications (CEA) Python API. It supports HP/TP equilibrium calculations and rocket nozzle performance calculations.

## Run in the lab network

From this directory:

```sh
docker compose up -d --build
```

The service joins the existing external `lab-net`, listens on container port `4173`, and publishes host port `4173` on `0.0.0.0` for direct LAN access. From another container on `lab-net` (including cloudflared), use:

```text
http://lab-cea:4173
```

From your LAN, use `http://<server-lan-ip>:4173`. Configure your Cloudflare Tunnel ingress to route to `http://lab-cea:4173` manually if desired. Check the service with `docker compose ps` or `docker compose logs -f cea`.

The image compiles the Python API from `../../rocket/ceav3/source`; the source tree is included in the Docker build context, and its local build artifacts are excluded. Node.js serves the interface and API; each calculation runs the CEA Python binding against its bundled thermodynamic database.

## Development

Requires Node.js 22, Python 3.11+, CMake, Ninja, and a Fortran compiler. Install the CEA Python package from `../../rocket/ceav3/source`, then:

```sh
npm install
npm run dev
```

Vite serves the UI on `5173` and proxies `/api` requests to the TypeScript API on `4174`.

## API reference

- [NASA CEA Python API](https://nasa.github.io/cea/interfaces/python_api.html)
- [NASA CEA quick start](https://nasa.github.io/cea/quick_start.html)

CEA's native unit conventions apply: pressure in bar, temperature in kelvin, and rocket specific impulse in m/s. The UI displays units alongside results.
