## [v1.2.2](https://github.com/docling-project/docling-serve/releases/tag/v1.2.2) - 2025-08-13

### Fix

* Update of transformers module to 4.55.1 ([#316](https://github.com/docling-project/docling-serve/issues/316)) ([`7692eb2`](https://github.com/docling-project/docling-serve/commit/7692eb26006fd4deaa021180c99e23a1b65de506))

## [v1.2.1](https://github.com/docling-project/docling-serve/releases/tag/v1.2.1) - 2025-08-13

### Fix

* Handling of vlm model options and update deps ([#314](https://github.com/docling-project/docling-serve/issues/314)) ([`8b470cb`](https://github.com/docling-project/docling-serve/commit/8b470cba8ef500c271eb84c8368c8a1a1a5a6d6a))
* Add missing response type in sync endpoints ([#309](https://github.com/docling-project/docling-serve/issues/309)) ([`8048f45`](https://github.com/docling-project/docling-serve/commit/8048f4589a91de2b2b391ab33a326efd1b29f25b))

### Documentation

* Update readme to use v1 ([#306](https://github.com/docling-project/docling-serve/issues/306)) ([`b3058e9`](https://github.com/docling-project/docling-serve/commit/b3058e91e0c56e27110eb50f22cbdd89640bf398))
* Update deployment examples to use v1 API ([#308](https://github.com/docling-project/docling-serve/issues/308)) ([`63da9ee`](https://github.com/docling-project/docling-serve/commit/63da9eedebae3ad31d04e65635e573194e413793))
* Fix typo in v1 migration instructions ([#307](https://github.com/docling-project/docling-serve/issues/307)) ([`b15dc25`](https://github.com/docling-project/docling-serve/commit/b15dc2529f78d68a475e5221c37408c3f77d8588))

## [v1.2.0](https://github.com/docling-project/docling-serve/releases/tag/v1.2.0) - 2025-08-07

### Feature

* Workers without shared models and convert params ([#304](https://github.com/docling-project/docling-serve/issues/304)) ([`db3fdb5`](https://github.com/docling-project/docling-serve/commit/db3fdb5bc1a0ae250afd420d737abc4071a7546c))
* Add rocm image build support and fix cuda ([#292](https://github.com/docling-project/docling-serve/issues/292)) ([`fd1b987`](https://github.com/docling-project/docling-serve/commit/fd1b987e8dc174f1a6013c003dde33e9acbae39a))

## [v1.1.0](https://github.com/docling-project/docling-serve/releases/tag/v1.1.0) - 2025-07-30

### Feature

* Add docling-mcp in the distribution ([#290](https://github.com/docling-project/docling-serve/issues/290)) ([`ecb1874`](https://github.com/docling-project/docling-serve/commit/ecb1874a507bef83d102e0e031e49fed34298637))
* Add 3.0 openapi endpoint ([#287](https://github.com/docling-project/docling-serve/issues/287)) ([`ec594d8`](https://github.com/docling-project/docling-serve/commit/ec594d84fe36df23e7d010a2fcf769856c43600b))
* Add new source and target ([#270](https://github.com/docling-project/docling-serve/issues/270)) ([`3771c1b`](https://github.com/docling-project/docling-serve/commit/3771c1b55403bd51966d07d8f760d5c4fbcc1760))

### Fix

* Referenced paths relative to zip root ([#289](https://github.com/docling-project/docling-serve/issues/289)) ([`1333f71`](https://github.com/docling-project/docling-serve/commit/1333f71c9c6495342b2169d574e921f828446f15))

## [v1.0.1](https://github.com/docling-project/docling-serve/releases/tag/v1.0.1) - 2025-07-21

### Fix

* Docling update v2.42.0 ([#277](https://github.com/docling-project/docling-serve/issues/277)) ([`8706706`](https://github.com/docling-project/docling-serve/commit/8706706e8797b0a06ec4baa7cf87988311be68b6))

### Documentation

* Typo in README ([#276](https://github.com/docling-project/docling-serve/issues/276)) ([`766adb2`](https://github.com/docling-project/docling-serve/commit/766adb248113c7bd5144d14b3c82929a2ad29f8e))

## [v1.0.0](https://github.com/docling-project/docling-serve/releases/tag/v1.0.0) - 2025-07-14

### Feature

* V1 api with list of sources and target ([#249](https://github.com/docling-project/docling-serve/issues/249)) ([`56e328b`](https://github.com/docling-project/docling-serve/commit/56e328baf76b4bb0476fc6ca820b52034e4f97bf))
* Use orchestrators from jobkit ([#248](https://github.com/docling-project/docling-serve/issues/248)) ([`daa924a`](https://github.com/docling-project/docling-serve/commit/daa924a77e56d063ef17347dfd8a838872a70529))

### Breaking

* v1 api with list of sources and target ([#249](https://github.com/docling-project/docling-serve/issues/249)) ([`56e328b`](https://github.com/docling-project/docling-serve/commit/56e328baf76b4bb0476fc6ca820b52034e4f97bf))
* use orchestrators from jobkit ([#248](https://github.com/docling-project/docling-serve/issues/248)) ([`daa924a`](https://github.com/docling-project/docling-serve/commit/daa924a77e56d063ef17347dfd8a838872a70529))

## [v0.16.1](https://github.com/docling-project/docling-serve/releases/tag/v0.16.1) - 2025-07-07

### Fix

* Upgrade deps including, docling v2.40.0 with locks in models init ([#264](https://github.com/docling-project/docling-serve/issues/264)) ([`bfde1a0`](https://github.com/docling-project/docling-serve/commit/bfde1a0991c2da53b72c4f131ff74fa10f6340de))
* Missing tesseract osd ([#263](https://github.com/docling-project/docling-serve/issues/263)) ([`eb3892e`](https://github.com/docling-project/docling-serve/commit/eb3892ee141eb2c941d580b095d8a266f2d2610c))
* Properly load models at boot ([#244](https://github.com/docling-project/docling-serve/issues/244)) ([`149a8cb`](https://github.com/docling-project/docling-serve/commit/149a8cb1c0a16c1e0b7d17f40b88b4d6e8f0109d))

### Documentation

* Fix typo ([#259](https://github.com/docling-project/docling-serve/issues/259)) ([`93b8471`](https://github.com/docling-project/docling-serve/commit/93b84712b2c6d180908a197847b52b217a7ff05f))
* Change the doc example ([#258](https://github.com/docling-project/docling-serve/issues/258)) ([`c45b937`](https://github.com/docling-project/docling-serve/commit/c45b93706466a073ab4a5c75aa8a267110873e26))
* Update typo ([#247](https://github.com/docling-project/docling-serve/issues/247)) ([`50e431f`](https://github.com/docling-project/docling-serve/commit/50e431f30fbffa33f43727417fe746d20cbb9d6b))

## [v0.16.0](https://github.com/docling-project/docling-serve/releases/tag/v0.16.0) - 2025-06-25

### Feature

* Package updates and more cuda images ([#229](https://github.com/docling-project/docling-serve/issues/229)) ([`30aca92`](https://github.com/docling-project/docling-serve/commit/30aca92298ab0d86bb4debcfcacb2dd8b9040a27))

### Documentation

* Update example resources and improve README ([#231](https://github.com/docling-project/docling-serve/issues/231)) ([`80755a7`](https://github.com/docling-project/docling-serve/commit/80755a7d5955f7d0c53df8e558fdd852dd1f5b75))

## [v0.15.0](https://github.com/docling-project/docling-serve/releases/tag/v0.15.0) - 2025-06-17

### Feature

* Use redocs and scalar as api docs ([#228](https://github.com/docling-project/docling-serve/issues/228)) ([`873d05a`](https://github.com/docling-project/docling-serve/commit/873d05aefe141c63b9c1cf53b23b4fa8c96de05d))

### Fix

* "tesserocr" instead of "tesseract_cli" in usage docs ([#223](https://github.com/docling-project/docling-serve/issues/223)) ([`196c5ce`](https://github.com/docling-project/docling-serve/commit/196c5ce42a04d77234a4212c3d9b9772d2c2073e))

## [v0.14.0](https://github.com/docling-project/docling-serve/releases/tag/v0.14.0) - 2025-06-17

### Feature

* Read supported file extensions from docling ([#214](https://github.com/docling-project/docling-serve/issues/214)) ([`524f6a8`](https://github.com/docling-project/docling-serve/commit/524f6a8997b86d2f869ca491ec8fb40585b42ca4))

### Fix

* Typo in Headline ([#220](https://github.com/docling-project/docling-serve/issues/220)) ([`d5455b7`](https://github.com/docling-project/docling-serve/commit/d5455b7f66de39ea1f8b8927b5968d2baa23ca88))

## [v0.13.0](https://github.com/docling-project/docling-serve/releases/tag/v0.13.0) - 2025-06-04

### Feature

* Upgrade docling to 2.36 ([#212](https://github.com/docling-project/docling-serve/issues/212)) ([`ffea347`](https://github.com/docling-project/docling-serve/commit/ffea34732b24fdd438fabd6df02d3d9ce66b4534))

## [v0.12.0](https://github.com/docling-project/docling-serve/releases/tag/v0.12.0) - 2025-06-03

### Feature

* Export annotations in markdown and html (Docling upgrade) ([#202](https://github.com/docling-project/docling-serve/issues/202)) ([`c4c41f1`](https://github.com/docling-project/docling-serve/commit/c4c41f16dff83c5d2a0b8a4c625b5de19b36b7c5))

### Fix

* Processing complex params in multipart-form ([#210](https://github.com/docling-project/docling-serve/issues/210)) ([`7066f35`](https://github.com/docling-project/docling-serve/commit/7066f3520a88c07df1c80a0cc6c4339eaac4d6a7))

### Documentation

* Add openshift replicasets examples ([#209](https://github.com/docling-project/docling-serve/issues/209)) ([`6a8190c`](https://github.com/docling-project/docling-serve/commit/6a8190c315792bd1e0e2b0af310656baaa5551e5))

## [v0.11.0](https://github.com/docling-project/docling-serve/releases/tag/v0.11.0) - 2025-05-23

### Feature

* Page break placeholder in markdown exports options ([#194](https://github.com/docling-project/docling-serve/issues/194)) ([`32b8a80`](https://github.com/docling-project/docling-serve/commit/32b8a809f348bf9fbde657f93589a56935d3749d))
* Clear results registry ([#192](https://github.com/docling-project/docling-serve/issues/192)) ([`de002df`](https://github.com/docling-project/docling-serve/commit/de002dfcdc111c942a08b156c84b7fa22b3fbaf3))
* Upgrade to Docling 2.33.0 ([#198](https://github.com/docling-project/docling-serve/issues/198)) ([`abe5aa0`](https://github.com/docling-project/docling-serve/commit/abe5aa03f54d44ecf5c6d76e3258028997a53e68))
* Api to trigger offloading the models ([#188](https://github.com/docling-project/docling-serve/issues/188)) ([`00be428`](https://github.com/docling-project/docling-serve/commit/00be4284904d55b78c75c5475578ef11c2ade94c))
* Figure annotations @ docling components 0.0.7 ([#181](https://github.com/docling-project/docling-serve/issues/181)) ([`3ff1b2f`](https://github.com/docling-project/docling-serve/commit/3ff1b2f9834aca37472a895a0e3da47560457d77))

### Fix

* Usage of hashlib for FIPS ([#171](https://github.com/docling-project/docling-serve/issues/171)) ([`8406fb9`](https://github.com/docling-project/docling-serve/commit/8406fb9b59d83247b8379974cabed497703dfc4d))

### Documentation

* Example and instructions on how to load model weights to persistent volume ([#197](https://github.com/docling-project/docling-serve/issues/197)) ([`3f090b7`](https://github.com/docling-project/docling-serve/commit/3f090b7d15eaf696611d89bbbba5b98569610828))
* Async api usage and fixes ([#195](https://github.com/docling-project/docling-serve/issues/195)) ([`21c1791`](https://github.com/docling-project/docling-serve/commit/21c1791e427f5b1946ed46c68dfda03c957dca8f))

## [v0.10.1](https://github.com/docling-project/docling-serve/releases/tag/v0.10.1) - 2025-04-30

### Fix

* Avoid missing specialized keys in the options hash ([#166](https://github.com/docling-project/docling-serve/issues/166)) ([`36787bc`](https://github.com/docling-project/docling-serve/commit/36787bc0616356a6199da618d8646de51636b34e))
* Allow users to set the area threshold for picture descriptions ([#165](https://github.com/docling-project/docling-serve/issues/165)) ([`509f488`](https://github.com/docling-project/docling-serve/commit/509f4889f8ed4c0f0ce25bec4126ef1f1199797c))
* Expose max wait time in sync endpoints ([#164](https://github.com/docling-project/docling-serve/issues/164)) ([`919cf5c`](https://github.com/docling-project/docling-serve/commit/919cf5c0414f2f11eb8012f451fed7a8f582b7ad))
* Add flash-attn for cuda images ([#161](https://github.com/docling-project/docling-serve/issues/161)) ([`35c2630`](https://github.com/docling-project/docling-serve/commit/35c2630c613cf229393fc67b6938152b063ff498))

## [v0.10.0](https://github.com/docling-project/docling-serve/releases/tag/v0.10.0) - 2025-04-28

### Feature

* Add support for file upload and return as file in async endpoints ([#152](https://github.com/docling-project/docling-serve/issues/152)) ([`c65f3c6`](https://github.com/docling-project/docling-serve/commit/c65f3c654c76c6b64b6aada1f0a153d74789d629))

### Documentation

* Fix new default pdf_backend ([#158](https://github.com/docling-project/docling-serve/issues/158)) ([`829effe`](https://github.com/docling-project/docling-serve/commit/829effec1a1b80320ccaf2c501be8015169b6fa3))
* Fixing small typo in docs ([#155](https://github.com/docling-project/docling-serve/issues/155)) ([`14bafb2`](https://github.com/docling-project/docling-serve/commit/14bafb26286b94f80b56846c50d6e9a6d99a9763))

## [v0.9.0](https://github.com/docling-project/docling-serve/releases/tag/v0.9.0) - 2025-04-25

### Feature

* Expose picture description options ([#148](https://github.com/docling-project/docling-serve/issues/148)) ([`4c9571a`](https://github.com/docling-project/docling-serve/commit/4c9571a052d5ec0044e49225bc5615e13cdb0a56))
* Add parameters for Kubeflow pipeline engine (WIP) ([#107](https://github.com/docling-project/docling-serve/issues/107)) ([`26bef5b`](https://github.com/docling-project/docling-serve/commit/26bef5bec060f0afd8d358816b68c3f2c0dd4bc2))

### Fix

* Produce image artifacts in referenced mode ([#151](https://github.com/docling-project/docling-serve/issues/151)) ([`71c5fae`](https://github.com/docling-project/docling-serve/commit/71c5fae505366459fd481d2ecdabc5ebed94d49c))

### Documentation

* Vlm and picture description options ([#149](https://github.com/docling-project/docling-serve/issues/149)) ([`91956cb`](https://github.com/docling-project/docling-serve/commit/91956cbf4e91cf82bb4d54ace397cdbbfaf594ba))

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
