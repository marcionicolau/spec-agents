import CodeBlock from "@theme/CodeBlock";

/**
 * Show a script from examples/docs. The scripts are run by tests/test_docs_examples.py, so what is shown works.
 * `source` is the raw file text (imported with `!!raw-loader!`), `file` the path shown as the block title.
 */
export default function Example({ source, file }) {
  return (
    <CodeBlock language="python" title={file} showLineNumbers>
      {source.trim()}
    </CodeBlock>
  );
}
