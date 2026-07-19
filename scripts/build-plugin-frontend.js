#!/usr/bin/env node
/**
 * build-plugin-frontend.js — 将插件的 .vue SFC 编译为浏览器可加载的自包含 JS bundle。
 *
 * 用法：
 *   node scripts/build-plugin-frontend.js <plugin_dir>
 *
 * 示例：
 *   node scripts/build-plugin-frontend.js ./plugins/my_plugin
 *   node scripts/build-plugin-frontend.js ./plugins/my_plugin --clean
 *
 * 输入：<plugin_dir>/frontend/*.vue
 * 输出：<plugin_dir>/frontend/dist/*.js + _manifest.json
 *
 * 生成的 bundle 从宿主应用的 window.__zaoWu_vue 获取 Vue，
 * 无需在插件中打包 Vue。
 *
 * 限制：
 *   - 仅支持单文件组件（不自动跟踪子组件依赖）
 *   - <script setup> 中 import 子组件会被转为动态 import（需确保路径可访问）
 *   - 复杂的编译器宏（defineExpose 等）可能需要手动调整
 */

const fs = require('fs')
const path = require('path')

// ── 参数解析 ──────────────────────────────────────────────────────────

const args = process.argv.slice(2)
const clean = args.includes('--clean')
const pluginDir = args.find(a => !a.startsWith('--'))

if (!pluginDir) {
  console.error('Usage: node scripts/build-plugin-frontend.js <plugin_dir> [--clean]')
  process.exit(1)
}

const frontendDir = path.resolve(pluginDir, 'frontend')
if (!fs.existsSync(frontendDir)) {
  console.error(`Error: ${frontendDir} does not exist`)
  process.exit(1)
}

// ── 依赖加载 ──────────────────────────────────────────────────────────

let compileDom
try {
  compileDom = require(path.resolve(__dirname, '..', 'ZaoWu', 'node_modules', '@vue', 'compiler-dom')).compile
} catch {
  try {
    compileDom = require('@vue/compiler-dom').compile
  } catch {
    console.error('Error: @vue/compiler-dom not found. Run "npm install" in ZaoWu/ first.')
    process.exit(1)
  }
}

// ── 工具函数 ──────────────────────────────────────────────────────────

const OUT_DIR = path.join(frontendDir, 'dist')

function parseSFC(source) {
  const blocks = { template: '', script: '', style: '' }

  const tplMatch = source.match(/<template>([\s\S]*?)<\/template>/)
  if (tplMatch) blocks.template = tplMatch[1].trim()

  const scriptMatch = source.match(/<script\s+setup[^>]*>([\s\S]*?)<\/script>/)
  if (scriptMatch) {
    blocks.script = scriptMatch[1].trim()
  } else {
    const plainScript = source.match(/<script>([\s\S]*?)<\/script>/)
    if (plainScript) blocks.script = plainScript[1].trim()
  }

  const styleMatch = source.match(/<style\s+scoped[^>]*>([\s\S]*?)<\/style>/)
  if (styleMatch) blocks.style = styleMatch[1].trim()
  else {
    const plainStyle = source.match(/<style>([\s\S]*?)<\/style>/)
    if (plainStyle) blocks.style = plainStyle[1].trim()
  }

  return blocks
}

function compileVueTemplate(templateCode) {
  const { code } = compileDom(templateCode, {
    mode: 'function',
    whitespace: 'condense',
  })

  // compile() with mode:'function' produces:
  //   const _Vue = Vue
  //   return function render(_ctx, _cache) { ... }
  // We need Vue to resolve to __zaoWu_vue, so prepend an alias.
  return `const Vue = __zaoWu_vue;\n${code}`
}

function transformScriptSetup(code) {
  let result = code

  // 0. 去除 TypeScript 类型注解
  //    ref<any[]>([])  → ref([])
  //    const x: string = 'a'  → const x = 'a'
  //    as Type  → (removed)
  result = result.replace(/<[^>]+>/g, '')                              // 泛型 <T, U>
  result = result.replace(/:\s*\w+(\[\])?\s*(?=[=,;)\n])/g, '')       // 类型注解 : Type
  result = result.replace(/\bas\s+\w+/g, '')                          // as Type

  // 1. Vue imports → 从 __zaoWu_vue 解构
  result = result.replace(
    /import\s*\{([^}]+)\}\s*from\s*['"]vue['"]/g,
    (_, names) => `const { ${names.trim()} } = __zaoWu_vue`,
  )

  // 2. 其他相对 import → 动态 import
  //    import Foo from './Foo.vue'  →  const { default: Foo } = await import('./Foo.js')
  //    import { bar } from './utils' →  const { bar } = await import('./utils.js')
  result = result.replace(
    /import\s+(\{[^}]+\}|(\w+))\s+from\s+['"](\.[^'"]+)['"]/g,
    (match, destructured, defaultImport, relPath) => {
      // 将 .vue 扩展名转为 .js
      const jsPath = relPath.replace(/\.vue$/, '.js')
      if (defaultImport) {
        return `const { default: ${defaultImport} } = await import('${jsPath}')`
      }
      return `const ${destructured.trim()} = await import('${jsPath}')`
    },
  )

  // 3. defineProps / defineEmits 宏 → 运行时版本
  result = result.replace(
    /const\s+(\w+)\s*=\s*defineProps\s*\(\s*(\{[\s\S]*?\})\s*\)\s*/g,
    (_, name, schema) => `const ${name} = __zaoWu_vue.defineProps(${schema})\n`,
  )
  result = result.replace(
    /defineProps\s*\(\s*(\{[\s\S]*?\})\s*\)/g,
    (_, schema) => `__zaoWu_vue.defineProps(${schema})`,
  )
  result = result.replace(
    /const\s+(\w+)\s*=\s*defineEmits\s*\(\s*(\[[\s\S]*?\]|\{[\s\S]*?\})\s*\)\s*/g,
    (_, name, schema) => `const ${name} = __zaoWu_vue.defineEmits(${schema})\n`,
  )
  result = result.replace(
    /defineEmits\s*\(\s*(\[[\s\S]*?\]|\{[\s\S]*?\})\s*\)/g,
    (_, schema) => `__zaoWu_vue.defineEmits(${schema})`,
  )

  return result
}

function buildBundle(renderFn, scriptCode, styleCode) {
  const injectStyle = styleCode
    ? `
  const __style = document.createElement('style');
  __style.textContent = ${JSON.stringify(styleCode)};
  document.head.appendChild(__style);`
    : ''

  // renderFn is the output of @vue/compiler-dom compile() with mode:'function'
  // It produces: const Vue = __zaoWu_vue; const _Vue = Vue; return function render(...) { ... }
  // We use defineComponent + setup() to properly handle Composition API lifecycle hooks.
  const setupReturn = scriptCode
    ? `  setup() {
${scriptCode}
    return { ${extractTopLevelNames(scriptCode).join(', ')} };
  }`
    : ''

  return `// Auto-generated by build-plugin-frontend.js — do not edit
const __zaoWu_vue = window.__zaoWu_vue;

const __renderFn = (() => {
  ${renderFn}
})();

export default __zaoWu_vue.defineComponent({
${setupReturn}
  render: __renderFn,
});
${injectStyle}
`
}

/**
 * Extract only top-level variable/function names from script setup code.
 * Uses indentation heuristic: declarations at indent level 0 are top-level.
 */
function extractTopLevelNames(code) {
  const names = []
  const lines = code.split('\n')
  for (const line of lines) {
    // Skip indented lines (inside functions, blocks, etc.)
    if (/^\s{2,}/.test(line)) continue
    // Match const/let/var/function declarations
    const declMatch = line.match(/^(?:const|let|var)\s+(\w+)\s*[=:]/)
    if (declMatch) names.push(declMatch[1])
    const fnMatch = line.match(/^(?:async\s+)?function\s+(\w+)/)
    if (fnMatch) names.push(fnMatch[1])
  }
  return [...new Set(names)]
}

// ── 主流程 ────────────────────────────────────────────────────────────

function main() {
  console.log(`Building frontend bundles for: ${pluginDir}`)

  // Clean output directory
  if (clean && fs.existsSync(OUT_DIR)) {
    fs.rmSync(OUT_DIR, { recursive: true })
    console.log('  Cleaned output directory')
  }
  fs.mkdirSync(OUT_DIR, { recursive: true })

  // Scan .vue files
  const vueFiles = fs.readdirSync(frontendDir)
    .filter(f => f.endsWith('.vue'))
    .sort()

  if (vueFiles.length === 0) {
    console.log('  No .vue files found in frontend/')
    return
  }

  const manifest = {}

  for (const vueFile of vueFiles) {
    const vuePath = path.join(frontendDir, vueFile)
    const componentName = path.basename(vueFile, '.vue')
    console.log(`  Compiling: ${vueFile} → ${componentName}.js`)

    // Parse SFC
    const source = fs.readFileSync(vuePath, 'utf-8')
    const { template, script, style } = parseSFC(source)

    if (!template) {
      console.warn(`    Warning: no <template> block found, skipping`)
      continue
    }

    // Compile template → render function
    const renderFn = compileVueTemplate(template)

    // Transform script setup
    const transformedScript = script ? transformScriptSetup(script) : ''

    // Build bundle
    const bundle = buildBundle(renderFn, transformedScript, style)

    // Write output
    const outPath = path.join(OUT_DIR, `${componentName}.js`)
    fs.writeFileSync(outPath, bundle, 'utf-8')
    console.log(`    → ${path.relative(process.cwd(), outPath)}`)

    manifest[componentName] = `frontend/dist/${componentName}.js`
  }

  // Write manifest
  const manifestPath = path.join(OUT_DIR, '_manifest.json')
  fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2), 'utf-8')
  console.log(`  Manifest: ${path.relative(process.cwd(), manifestPath)}`)
  console.log(`  Done! ${Object.keys(manifest).length} component(s) built.`)
}

main()
