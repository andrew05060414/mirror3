# Mirror Info Platforms

This file tracks upstream sources used to maintain `mirrors.catalog.json`.

## Recommended platforms

- MirrorZ: <https://mirrorz.org>
  - Best for discovering commonly mirrored ecosystems and mirror sites.
- USTC mirror help: <https://mirrors.ustc.edu.cn/help/>
  - Detailed per-ecosystem docs and status pages.
- TUNA mirror help: <https://mirrors.tuna.tsinghua.edu.cn/help/>
  - Practical config guidance for many ecosystems.

## Ecosystem official references

- Go:
  - <https://raw.githubusercontent.com/goproxy/goproxy.cn/master/README.zh-CN.md>
- Rust:
  - <https://rsproxy.cn/>
- npm:
  - <https://web.npmmirror.com/>
- RubyGems:
  - <https://gems.ruby-china.com/>
- Composer:
  - <https://developer.aliyun.com/composer>
  - <https://packagist.phpcomposer.com>

## Maintenance suggestion

- Use a "seed list + speed test" strategy:
  1. Keep broad candidate mirrors in catalog.
  2. Auto-select fastest reachable mirror per tool.
  3. Remove mirrors with long-term failures based on periodic logs.
