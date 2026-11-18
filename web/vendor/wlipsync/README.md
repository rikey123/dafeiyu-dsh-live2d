# wLipSync WASM fix

Source: mrxz/wlipsync commit `177f3ac4095dbad81be0a800a8c6f975abe4ae04`, MIT license in this directory. The one-line fix in `src/main.c` copies all `MFCC_NUM` coefficients instead of the number of phoneme classes. The upstream scoring functions read all 12 coefficients.

Rebuild on Windows using wasi-sdk 27.0 LLVM 20.1.8, whose release archive SHA-256 is `4a576c13125c91996d8cc3b70b7ea0612c2044598d2795c9be100d15f874adf6`:

```powershell
./vendor/wlipsync/build.ps1 -Toolchain <path-to-wasi-sdk-bin>
```

The build uses the upstream compiler and linker flags, without the optional `wasm-opt` size optimization. The checked-in WASM SHA-256 is `7f7ba6dcf48ea196806feeaf0b751cc26b40b91bf0a43c70557f783d6924bf69` and is loaded through the official `wlipsync@1.3.1` configuration API. Recalibration and independent phoneme accuracy testing are required after changing the classifier.

`json2bin.mjs` is the upstream 1.3.1 MIT conversion tool with its WASM path changed to this corrected build. Regenerate after profile calibration with `node vendor/wlipsync/json2bin.mjs src/avatar/lipsync/local-vits-profile.json src/avatar/lipsync/local-vits-profile.bin`. The current local profile remains imperfect for E/O and is not a general Chinese phoneme model.
