// Browser unit harness: render the actual hook; dependencies can settle after abort.
import React from "react";
import { createRoot } from "react-dom/client";
import { useReviewJob } from "../../src/hooks/useReviewJob";

export function mount() {
  const deferred = () => {
    let resolve, reject;
    const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
    return { promise, resolve, reject };
  };
  const h = window.reviewHarness = {
    sessions: [], submissions: [], polls: [], errors: [], auth: [], history: [],
    deferred,
    session: { access_token: "synthetic", user: { id: "test" }, expires_at: 9999999999 },
    ensureFreshSession: () => {
      const pending = deferred();
      h.sessions.push(pending);
      return pending.promise;
    },
  };
  function Harness() {
    const review = useReviewJob({
      form: { target: "https://github.com/example/test", ai_model: "", ai_token_budget: 20000 },
      authSession: h.session, setAuthSession: value => h.auth.push(value),
      ensureFreshSession: h.ensureFreshSession, isGuestMode: false, isChinese: false,
      runPhases: [{ key: "analyzing" }], loadProjectList: (...args) => h.history.push(args),
    });
    h.review = review;
    return <>
      <button onClick={() => review.runReview({ preventDefault() {} }).catch(error => h.errors.push(error.message))}>Run</button>
      <button onClick={review.resetReview}>Reset</button>
      <button onClick={review.loadDemoReport}>Demo</button>
      <output>{JSON.stringify({ status: review.status, running: review.isRunning,
        report: review.report, pending: review.pendingJob })}</output>
    </>;
  }
  createRoot(document.getElementById("root")).render(<Harness />);
}
