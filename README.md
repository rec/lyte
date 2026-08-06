# lyte

Small, dependency-free Python client for Twinkly lights born
from personal frustration.

I was the principle developer on the classic Bibliopixel package but
the copyright holder decided to call it in, and so I left the project
but I want to preserve my animations for the lights I have.

But the only library for the Twinkly protocol uses all sorts of heavy dependencies,
in particular zeromq, which means only one client per network, which is silly.

This package uses prior reverse engineering work on the Twinkly protocol,
but in a stripped-down build.

This is a proof of concept with:

- UDP discovery on port 5555
- HTTP authentication and JSON API calls on port 80
- generation 2 realtime UDP frames on port 7777

Run the diagnostic:

```sh
lyte diagnostic
```

Run the Hamiltonian streamer:

```sh
lyte animate hamiltonian --speed 80
```

Increase playback speed:

```sh
lyte animate hamiltonian --speed 120
```
