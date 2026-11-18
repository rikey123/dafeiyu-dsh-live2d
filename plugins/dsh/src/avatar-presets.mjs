/** Public, pinned asset metadata shared by the installer and its browser UI.
 * The model remains on its upstream host, never bundled or rehosted here.
 */
export const DEFAULT_AVATAR = Object.freeze({
  id: 'deepseek-chan',
  name: '大肥鱼 · DeepSeek-chan',
  revision: '824e03aa38c18c9eb2a9ee1344e3c8bed6671b1f',
  repositoryUrl: 'https://github.com/YJackie-Li/DeepSeek-chan',
  authorReleaseUrl: 'https://www.bilibili.com/video/BV1KmxY66EZ3/',
  licenseUrl: 'https://github.com/YJackie-Li/DeepSeek-chan/blob/824e03aa38c18c9eb2a9ee1344e3c8bed6671b1f/README.md',
  url: 'https://github.com/YJackie-Li/DeepSeek-chan/archive/824e03aa38c18c9eb2a9ee1344e3c8bed6671b1f.zip',
  sha256: '79f4afc36d07c5a75c6181804e2a788ea5330606054046ebaa77bfee930d8008',
  bytes: 49738232,
  maxBytes: 64 * 1024 * 1024,
  // Verified download bytes, not an upstream-published checksum or a claim
  // that the repository maintainer has been verified as the original artist.
  checksumVerifiedOn: '2026-11-18',
});
