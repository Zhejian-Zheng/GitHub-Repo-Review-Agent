import React from "react";
export function MarkdownSummary({ text }) {
  const lines = (text || "").split("\n");
  const blocks = [];
  let list = [];

  const flushList = () => {
    if (!list.length) return;
    blocks.push({ type: "list", items: list });
    list = [];
  };

  lines.forEach((line) => {
    const trimmed = line.trim();
    if (!trimmed) {
      flushList();
      return;
    }
    const normalizedHeading = normalizeReviewHeading(trimmed);
    if (normalizedHeading) {
      flushList();
      blocks.push({ type: "heading", text: normalizedHeading });
      return;
    }
    if (trimmed.startsWith("### ")) {
      flushList();
      blocks.push({ type: "heading", text: trimmed.slice(4) });
      return;
    }
    if (trimmed.startsWith("## ")) {
      flushList();
      blocks.push({ type: "heading", text: trimmed.slice(3) });
      return;
    }
    if (trimmed === "-" || trimmed === "*") {
      return;
    }
    if (trimmed.startsWith("- ") || trimmed.startsWith("* ")) {
      const listItem = trimmed.slice(2).trim();
      if (listItem) {
        list.push(listItem);
      }
      return;
    }
    flushList();
    blocks.push({ type: "paragraph", text: trimmed });
  });
  flushList();

  return (
    <div className="markdown-summary">
      {blocks.map((block, index) => {
        if (block.type === "heading") {
          return <h4 key={index}>{renderInlineMarkdown(block.text)}</h4>;
        }
        if (block.type === "list") {
          return (
            <ul key={index}>
              {block.items.map((item, itemIndex) => (
                <li key={`${item}-${itemIndex}`}>{renderInlineMarkdown(item)}</li>
              ))}
            </ul>
          );
        }
        return <p key={index}>{renderInlineMarkdown(block.text)}</p>;
      })}
    </div>
  );
}

function normalizeReviewHeading(trimmed) {
  if (/^(?:#{1,6}\s*)?简历亮点\s*[:：]?\s*$/.test(trimmed)) {
    return "项目亮点";
  }
  if (/^(?:#{1,6}\s*)?Resume Pitch\s*[:：]?\s*$/i.test(trimmed)) {
    return "Project Highlights";
  }
  return "";
}

function renderInlineMarkdown(text) {
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g).filter(Boolean);
  return parts.map((part, index) => {
    if (part.startsWith("`") && part.endsWith("`")) {
      return <code key={index}>{part.slice(1, -1)}</code>;
    }
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }
    return <React.Fragment key={index}>{part}</React.Fragment>;
  });
}

