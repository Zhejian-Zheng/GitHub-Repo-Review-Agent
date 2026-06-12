import { reportCopy } from "./reportCopy";

export function renderStaticMarkdown(report, language) {
  const copy = reportCopy[language] ?? reportCopy.en;
  const lines = [
    `# ${copy.repositoryReview}: ${report.repo_name}`,
    "",
    `${copy.generated}: \`${report.generated_at}\``,
    "",
    `## ${copy.executiveSummary}`,
    "",
    ...(report.overview ?? []).map((item) => `- ${item}`),
    "",
    `## ${copy.metrics}`,
    "",
    ...Object.entries(copy.metricLabels).map(
      ([key, label]) => `- ${label}: \`${report.metrics?.[key] ?? 0}\``
    ),
    `- Languages: \`${Object.entries(report.metrics?.languages ?? {})
      .map(([name, count]) => `${name}: ${count}`)
      .join(", ")}\``,
    "",
    `## ${copy.frameworkSignals}`,
    ""
  ];

  Object.entries(report.framework_signals ?? {}).forEach(([label, evidence]) => {
    lines.push(`- **${label}**: ${(evidence ?? []).slice(0, 4).join(", ")}`);
  });

  if (report.ai_review) {
    lines.push(
      "",
      `## ${copy.aiReview}`,
      "",
      `- ${copy.provider}: \`${report.ai_review.provider}\``,
      `- ${copy.model}: \`${report.ai_review.model}\``,
      `- ${copy.status}: \`${report.ai_review.status}\``,
      "",
      report.ai_review.summary,
      ""
    );
  }

  if (report.agent_trace?.length) {
    lines.push("", `## ${copy.agentTrace}`, "");
    report.agent_trace.forEach((step, index) => {
      lines.push(
        `### ${copy.step} ${index + 1}: \`${step.tool}\``,
        "",
        `- Thought: ${step.thought}`,
        `- Input: \`${JSON.stringify(step.tool_input)}\``,
        `- Observation: ${step.observation}`,
        ""
      );
    });
  }

  lines.push("", `## ${copy.findings}`, "");
  (report.findings ?? []).forEach((finding, index) => {
    lines.push(
      `### ${index + 1}. ${finding.title}`,
      "",
      `- Severity: \`${finding.severity}\``,
      `- Category: \`${finding.category}\``,
      `- ${copy.evidence}:`
    );
    (finding.evidence ?? []).forEach((item) => lines.push(`  - ${item}`));
    if ((finding.evidence_paths ?? []).length) {
      lines.push(`- ${copy.evidencePaths}:`);
      finding.evidence_paths.forEach((path) => lines.push(`  - \`${path}\``));
    }
    lines.push(`- ${copy.recommendation}:`, `  - ${finding.recommendation}`, "");
  });

  lines.push("", `## ${copy.issueBacklog}`, "");
  const actionableFindings = (report.findings ?? []).filter((finding) => finding.severity !== "info");
  if (actionableFindings.length) {
    actionableFindings.forEach((finding) => {
      lines.push(`- [${finding.severity.toUpperCase()}] ${finding.title} - ${finding.recommendation}`);
    });
  } else {
    lines.push(`- ${copy.noIssues}`);
  }

  lines.push("");
  return lines.join("\n");
}
