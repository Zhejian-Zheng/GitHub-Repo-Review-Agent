import React, { useEffect, useRef, useState } from "react";
export function ReportQuestionForm({ language, onAsk, provider }) {
  const chinese = language === "zh-CN";
  const [question, setQuestion] = useState("");
  const [response, setResponse] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const request = useRef(null);
  useEffect(() => () => { request.current?.abort(); request.current = null; }, []);
  const submit = async event => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    const isCurrent = () => request.current === controller && !controller.signal.aborted;
    event.preventDefault(); setBusy(true); setError(""); setResponse(null);
    try {
      const answer = await onAsk(question, { signal: controller.signal });
      if (isCurrent()) setResponse(answer);
    }
    catch (failure) { if (isCurrent()) setError(failure.message); }
    finally { if (isCurrent()) setBusy(false); }
  };
  return <section className="report-questions">
    <h3>{chinese ? "询问这份报告" : "Ask about this report"}</h3>
    <p>{chinese ? "使用所选模型" : "Uses selected provider"}: {provider}</p>
    <form onSubmit={submit}><label>{chinese ? "问题" : "Question"}
      <textarea aria-label="Report question" required maxLength={2000} value={question} onChange={event => setQuestion(event.target.value)} />
    </label><button type="submit" disabled={busy || !question.trim()}>{chinese ? "询问报告" : "Ask about report"}</button></form>
    {error ? <p role="alert">{error}</p> : null}
    {response ? <div className="report-question-answer" role="status">
      <p>{response.answer}</p>
      {(response.citations || []).map((citation, index) => <blockquote key={index}>
        <code>{(citation.paths || [citation.path]).filter(Boolean).join(", ")}{citation.start_line && (citation.paths || [citation.path]).length === 1 ? `:${citation.start_line}–${citation.end_line || citation.start_line}` : ""}</code>
        <pre>{citation.evidence}</pre>
      </blockquote>)}
      {(response.limitations || []).map((limitation, index) => <p key={index}>{limitation}</p>)}
    </div> : null}
  </section>;
}

