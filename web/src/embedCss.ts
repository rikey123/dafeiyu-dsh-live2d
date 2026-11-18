/** Adapt the standalone stylesheet to a size-contained shadow tree. */
export function shadowCss(css: string) {
  return css
    .replace(/:root(\[[^\]]+\])?/g, (_, attr: string | undefined) => attr ? `:host(${attr})` : ':host')
    .replace(/html\s*,\s*body\s*,\s*#root\s*\{/g, '.embed-container, #root {')
    .replace(/\bbody\s*\{/g, ':host {')
    .replace(/height:\s*100(?:d)?vh/g, 'height:100%')
    .replace(/@media\s*\(max-width\s*:/g, '@container (max-width:')
    + '\n:host { display: block; min-width: 0; line-height: normal; letter-spacing: normal; text-transform: none; }\n.embed-container { width: 100%; height: 100%; container-type: size; isolation: isolate; }\n'
}
