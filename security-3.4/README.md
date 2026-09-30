# Experimental WAHA restriction candidate

The TypeScript sources and patch are retained for review. They are not built or installed by the Debian package. `tests/test_waha_restricted.mjs` checks basic policy behavior with Node; it does not validate a full NestJS/upstream build, permit lifecycle or live messaging. Removed historical runners referred to source absent from this snapshot. Third-party notice: `patches/WAHA_CORE_LICENSE`.
