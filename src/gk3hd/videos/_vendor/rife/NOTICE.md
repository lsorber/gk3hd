RIFE 4.25 network and warp implementation copied without changes from
[HolyWu/vs-rife](https://github.com/HolyWu/vs-rife), commit
`3488617283db7c428a83ba4a19382285da698b6a` (MIT, see LICENSE).
`IFNet_HDv3_v4_25.py` is named `model.py` here.

The network originates from [hzwer/Practical-RIFE](https://github.com/hzwer/Practical-RIFE).
Weights are downloaded separately from the vs-rife model release and verified
by SHA-256 before safe, weights-only loading. No VapourSynth or upstream CLI
dependencies are required. GK3HD owns input timing, padding and output encoding.
