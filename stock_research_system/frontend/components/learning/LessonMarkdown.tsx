import ReactMarkdown, { type Components } from "react-markdown";

/** The page itself always owns the single `<h1>` (via `PageHeading`);
 * lesson content and tutor answers are free to start with their own
 * `# Heading`, so every markdown heading level is demoted by one to
 * avoid a second `<h1>` on the page. */
const DEMOTED_HEADINGS: Components = {
  h1: (props) => <h2 {...props} />,
  h2: (props) => <h3 {...props} />,
  h3: (props) => <h4 {...props} />,
  h4: (props) => <h5 {...props} />,
  h5: (props) => <h6 {...props} />,
  h6: (props) => <h6 {...props} />,
};

/** Renders lesson/tutor content as Markdown - deliberately does NOT
 * pass `rehype-raw` (or any plugin that would enable raw HTML), so any
 * `<script>`/HTML embedded in the source content is rendered as
 * literal, inert text rather than executed. */
export function LessonMarkdown({ content }: { content: string }) {
  return (
    <div className="prose prose-slate max-w-none prose-headings:font-semibold prose-a:text-primary">
      <ReactMarkdown components={DEMOTED_HEADINGS}>{content}</ReactMarkdown>
    </div>
  );
}
