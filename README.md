## Settings

copy / paste .env.example to .env and complete_
You can change the port Kpiten will be available on by changing the `KPITEN_PORT` variable in your `.env` file.

## How to run the app

```bash
docker compose up --build # running for the first time
docker compose up # if you want to see KpiTen logs
docker compose up -d # if you want to run the server without blocking your shell
```

## Caveats

- change the networks in the `docker-compose.yml` to whatever you need. if the networks don't exist, it won't work.
```yaml
# except for network configs, everything should remain unchanged
services:
  kpiten:
    build: 
      context: .
    image: kpiten
    ports:
      - ${KPITEN_PORT}:5000

    networks:
      - your_network
      - your_other_network
      ...

networks: # these should be changed to whatever network you need Kpiten to be in.
  your_network:
    external: true
  your_other_network:
    external: true
  ...
```

> **TIP** : Use `docker network ls` to list your networks and get the exact names.