# lyte

Small, dependency-free Python client for Twinkly generation 2 lights.

This project focuses only on the low-level protocol pieces:

- UDP discovery on port 5555
- HTTP authentication and JSON API calls on port 80
- generation 2 realtime UDP frames on port 7777

Run the diagnostic script from a checkout:

```sh
python3 scripts/lyte_diagnostic.py
```

If UDP discovery is blocked by the network, pass the light controller IP:

```sh
python3 scripts/lyte_diagnostic.py --host 192.168.1.50
```

Run the Hamiltonian streamer:

```sh
python3 scripts/lyte_hamiltonian.py --host 192.168.1.50
```

Increase playback speed:

```sh
python3 scripts/lyte_hamiltonian.py --host 192.168.1.50 --speed 80
```

Check the Hamiltonian sequence without connecting to lights:

```sh
python3 scripts/check_hamiltonian.py --n 32
```
