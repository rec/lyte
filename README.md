# lyte

Small, dependency-free Python client for Twinkly lights born
from personal frustration.

I was the principle developer on the classic Bibliopixel package but
the copyright holder decided to call it in, and so I left the project
but I want to preserve my animations for the lights I have.

But the only library for the Twinkly protocol uses all sorts of heavy dependencies,
in particular zeromq, which means only one client per network, which is silly.

This package uses the reverse engineering work of the xled package but in
a new a stripped build.

This is a proof of concept with:

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
python3 scripts/lyte_hamiltonian.py --host 192.168.1.50 --speed 80
```

Increase playback speed:

```sh
python3 scripts/lyte_hamiltonian.py --host 192.168.1.50 --speed 80
```
