## [v0.8.0](https://github.com/docling-project/docling-serve/releases/tag/v0.8.0) - 2025-04-22

### Feature

* Add option for vlm pipeline ([#143](https://github.com/docling-project/docling-serve/issues/143)) ([`ee89ee4`](https://github.com/docling-project/docling-serve/commit/ee89ee4daee5e916bd6a3bdb452f78934cd03f60))
* Expose more conversion options ([#142](https://github.com/docling-project/docling-serve/issues/142)) ([`6b3d281`](https://github.com/docling-project/docling-serve/commit/6b3d281f02905c195ab75f25bb39f5c4d4e7b680))
* **UI:** Change UI to use async endpoints ([#131](https://github.com/docling-project/docling-serve/issues/131)) ([`b598872`](https://github.com/docling-project/docling-serve/commit/b598872e5c48928ac44417a11bb7acc0e5c3f0c6))

### Fix

* **UI:** Use https when calling the api ([#139](https://github.com/docling-project/docling-serve/issues/139)) ([`57f9073`](https://github.com/docling-project/docling-serve/commit/57f9073bc0daf72428b068ea28e2bec7cd76c37b))
* Fix permissions in docker image ([#136](https://github.com/docling-project/docling-serve/issues/136)) ([`c1ce471`](https://github.com/docling-project/docling-serve/commit/c1ce4719c933179ba3c59d73d0584853bbd6fa6a))
* Picture caption visuals ([#129](https://github.com/docling-project/docling-serve/issues/129)) ([`5dfb75d`](https://github.com/docling-project/docling-serve/commit/5dfb75d3b9a7022d1daad12edbb8ec7bbf9aa264))

### Documentation

* Fix required permissions for oauth2-proxy requests ([#141](https://github.com/docling-project/docling-serve/issues/141)) ([`087417e`](https://github.com/docling-project/docling-serve/commit/087417e5c2387d4ed95500222058f34d8a8702aa))
* Update deployment examples ([#135](https://github.com/docling-project/docling-serve/issues/135)) ([`525a43f`](https://github.com/docling-project/docling-serve/commit/525a43ff6f04b7cc80f9dd6a0e653a8d8c4ab317))
* Fix image tag ([#124](https://github.com/docling-project/docling-serve/issues/124)) ([`420162e`](https://github.com/docling-project/docling-serve/commit/420162e674cc38b4c3c13673ffbee4c20a1b15f1))

## [v0.7.0](https://github.com/docling-project/docling-serve/releases/tag/v0.7.0) - 2025-03-31

### Feature

* Expose TLS settings and example deploy with oauth-proxy ([#112](https://github.com/docling-project/docling-serve/issues/112)) ([`7a0faba`](https://github.com/docling-project/docling-serve/commit/7a0fabae07020c2659dbb22c3b0359909051a74c))
* Offline static files ([#109](https://github.com/docling-project/docling-serve/issues/109)) ([`68772bb`](https://github.com/docling-project/docling-serve/commit/68772bb6f0a87b71094a08ff851f5754c6ca6163))
* Update to Docling 2.28 ([#106](https://github.com/docling-project/docling-serve/issues/106)) ([`20ec87a`](https://github.com/docling-project/docling-serve/commit/20ec87a63a99145bc0ad7931549af8a0c30db641))

### Fix

* Move ARGs to prevent cache invalidation ([#104](https://github.com/docling-project/docling-serve/issues/104)) ([`e30f458`](https://github.com/docling-project/docling-serve/commit/e30f458923d34c169db7d5a5c296848716e8cac4))

## [v0.6.0](https://github.com/docling-project/docling-serve/releases/tag/v0.6.0) - 2025-03-17

### Feature

* Expose options for new features ([#92](https://github.com/docling-project/docling-serve/issues/92)) ([`ec57b52`](https://github.com/docling-project/docling-serve/commit/ec57b528ed3f8e7b9604ff4cdf06da3d52c714dd))

### Fix

* Allow changes in CORS settings ([#100](https://github.com/docling-project/docling-serve/issues/100)) ([`422c402`](https://github.com/docling-project/docling-serve/commit/422c402bab7f05e46274ede11f234a19a62e093e))
* Avoid exploding options cache using lru and expose size parameter ([#101](https://github.com/docling-project/docling-serve/issues/101)) ([`ea09028`](https://github.com/docling-project/docling-serve/commit/ea090288d3eec4ea8fbdcd32a6a497a99c89189d))
* Increase timeout_keep_alive and allow parameter changes ([#98](https://github.com/docling-project/docling-serve/issues/98)) ([`07c48ed`](https://github.com/docling-project/docling-serve/commit/07c48edd5d9437219d9623e3d05bc5166c5bb85a))
* Add warning when using incompatible parameters ([#99](https://github.com/docling-project/docling-serve/issues/99)) ([`a212547`](https://github.com/docling-project/docling-serve/commit/a212547d28d6588c65e52000dc7bc04f3f77e69e))
* **ui:** Use --port parameter and avoid failing when image is not found ([#97](https://github.com/docling-project/docling-serve/issues/97)) ([`c76daac`](https://github.com/docling-project/docling-serve/commit/c76daac70c87da412f791666881e48b74688b060))

### Documentation

* Simplify README and move details to docs ([#102](https://github.com/docling-project/docling-serve/issues/102)) ([`fd8e40a`](https://github.com/docling-project/docling-serve/commit/fd8e40a00849771263d9b75b9a56f6caeccb8517))

## [v0.5.1](https://github.com/docling-project/docling-serve/releases/tag/v0.5.1) - 2025-03-10

### Fix

* Submodules in wheels ([#85](https://github.com/docling-project/docling-serve/issues/85)) ([`a92ad48`](https://github.com/docling-project/docling-serve/commit/a92ad48b287bfcb134011dc0fc3f91ee04e067ee))

## [v0.5.0](https://github.com/docling-project/docling-serve/releases/tag/v0.5.0) - 2025-03-07

### Feature

* Async api ([#60](https://github.com/docling-project/docling-serve/issues/60)) ([`82f8900`](https://github.com/docling-project/docling-serve/commit/82f890019745859699c1b01f9ccfb64cb7e37906))
* Display version in fastapi docs ([#78](https://github.com/docling-project/docling-serve/issues/78)) ([`ed851c9`](https://github.com/docling-project/docling-serve/commit/ed851c95fee5f59305ddc3dcd5c09efce618470b))

### Fix

* Remove uv from image, merge ARG and ENV declarations ([#57](https://github.com/docling-project/docling-serve/issues/57)) ([`c95db36`](https://github.com/docling-project/docling-serve/commit/c95db3643807a4dfb96d93c8e10d6eb486c49a30))
* **docs:** Remove comma in convert/source curl example ([#73](https://github.com/docling-project/docling-serve/issues/73)) ([`05df073`](https://github.com/docling-project/docling-serve/commit/05df0735d35a589bdc2a11fcdd764a10f700cb6f))

## [v0.4.0](https://github.com/docling-project/docling-serve/releases/tag/v0.4.0) - 2025-02-26

### Feature

* New container images ([#68](https://github.com/docling-project/docling-serve/issues/68)) ([`7e6d9cd`](https://github.com/docling-project/docling-serve/commit/7e6d9cdef398df70a5b4d626aeb523c428c10d56))
* Render DoclingDocument with npm docling-components in the example UI ([#65](https://github.com/docling-project/docling-serve/issues/65)) ([`c430d9b`](https://github.com/docling-project/docling-serve/commit/c430d9b1a162ab29104d86ebaa1ac5a5488b1f09))

## [v0.3.0](https://github.com/docling-project/docling-serve/releases/tag/v0.3.0) - 2025-02-19

### Feature

* Add new docling-serve cli ([#50](https://github.com/docling-project/docling-serve/issues/50)) ([`ec33a61`](https://github.com/docling-project/docling-serve/commit/ec33a61faa7846b9b7998fbf557ebe39a3b800f6))

### Fix

* Set DOCLING_SERVE_ARTIFACTS_PATH in images ([#53](https://github.com/docling-project/docling-serve/issues/53)) ([`4877248`](https://github.com/docling-project/docling-serve/commit/487724836896576ca4f98e84abf15fd1c383bec8))
* Set root UI path when behind proxy ([#38](https://github.com/docling-project/docling-serve/issues/38)) ([`c64a450`](https://github.com/docling-project/docling-serve/commit/c64a450bf9ba9947ab180e92bef2763ff710b210))
* Support python 3.13 and docling updates and switch to uv ([#48](https://github.com/docling-project/docling-serve/issues/48)) ([`ae3b490`](https://github.com/docling-project/docling-serve/commit/ae3b4906f1c0829b1331ea491f3518741cabff71))
