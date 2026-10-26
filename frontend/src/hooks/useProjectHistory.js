import { useEffect, useRef, useState } from "react";
import { fetchRepositories, fetchProjectDetail, saveFindingFeedback } from "../historyClient";

export function useProjectHistory(authSession, ensureFreshSession) {
  const [repositories, setRepositories] = useState([]);
  const [selectedRepository, setSelectedRepository] = useState(null);
  const [projectDetail, setProjectDetail] = useState(null);
  const [isHistoryLoading, setIsHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const detailRequest = useRef(null);
  const listRequest = useRef(null);
  const detailRefresh = useRef(0);
  const knownUserId = useRef(authSession?.user?.id);
  const startDetailRequest = () => {
    detailRequest.current?.abort();
    const controller = new AbortController();
    detailRequest.current = controller;
    return controller;
  };
  const detailRequestIsCurrent = controller =>
    detailRequest.current === controller && !controller.signal.aborted;
  useEffect(() => () => {
    detailRequest.current?.abort();
    detailRequest.current = null;
    listRequest.current?.abort();
    listRequest.current = null;
  }, []);
  useEffect(() => {
    const nextUserId = authSession?.user?.id;
    if (knownUserId.current === nextUserId) return;
    // Hydrating the user for an OAuth/URL session is not an account switch.
    // Aborting here would cancel the first history load without restarting it.
    const switchedAccount = Boolean(knownUserId.current);
    knownUserId.current = nextUserId;
    if (!switchedAccount) return;
    detailRequest.current?.abort();
    detailRequest.current = null;
    listRequest.current?.abort();
    listRequest.current = null;
    setRepositories([]);
    setSelectedRepository(null);
    setProjectDetail(null);
    setIsHistoryLoading(false);
    setHistoryError("");
  }, [authSession?.user?.id]);
  useEffect(() => {
    if (!authSession?.access_token) {
      setRepositories([]);
      setSelectedRepository(null);
      setProjectDetail(null);
      setIsHistoryLoading(false);
      setHistoryError("");
      return undefined;
    }

    let isMounted = true;
    loadProjectList(authSession.access_token, { silent: true, isMountedRef: () => isMounted });
    return () => {
      isMounted = false;
      listRequest.current?.abort();
    };
  }, [authSession?.access_token]);

  const loadProjectList = async (
    accessToken = authSession?.access_token,
    { silent = false, isMountedRef = () => true } = {}
  ) => {
    listRequest.current?.abort();
    const controller = new AbortController();
    listRequest.current = controller;
    const current = () => isMountedRef() && listRequest.current === controller && !controller.signal.aborted;
    const session = await ensureFreshSession(
      accessToken === authSession?.access_token ? authSession : { access_token: accessToken },
      { signal: controller.signal }
    );
    if (!session?.access_token || !current()) return;
    if (!silent) {
      setIsHistoryLoading(true);
    }
    setHistoryError("");
    try {
      const nextRepositories = await fetchRepositories(session.access_token, { signal: controller.signal });
      if (!current()) return;
      setRepositories(nextRepositories);
    } catch (error) {
      if (!current()) return;
      setHistoryError(error.message);
    } finally {
      if (!silent && current()) {
        setIsHistoryLoading(false);
      }
    }
  };

  const openProjectDetail = async (repository) => {
    if (!authSession?.access_token) return;
    const controller = startDetailRequest();
    setSelectedRepository(repository);
    setProjectDetail(null);
    setHistoryError("");
    setIsHistoryLoading(true);
    try {
      const session = await ensureFreshSession(authSession, { signal: controller.signal });
      if (!session?.access_token || !detailRequestIsCurrent(controller)) return;
      const detail = await fetchProjectDetail(repository.id, session.access_token, { signal: controller.signal });
      if (!detailRequestIsCurrent(controller)) return;
      setProjectDetail(detail);
      window.requestAnimationFrame(() => {
        if (detailRequestIsCurrent(controller)) {
          document.getElementById("project-detail")?.scrollIntoView({ behavior: "smooth", block: "start" });
        }
      });
    } catch (error) {
      if (detailRequestIsCurrent(controller)) setHistoryError(error.message);
    } finally {
      if (detailRequestIsCurrent(controller)) setIsHistoryLoading(false);
    }
  };

  const updateFeedback = async (finding, payload) => {
    const repository = selectedRepository;
    const controller = detailRequest.current;
    if (!repository || !controller || !detailRequestIsCurrent(controller)) {
      throw new Error("Select a project before saving a decision.");
    }
    const session = await ensureFreshSession(authSession, { signal: controller.signal });
    if (!detailRequestIsCurrent(controller)) {
      throw new Error("Project changed before the decision was saved.");
    }
    if (!session?.access_token) throw new Error("Sign in before saving a decision.");
    // Each explicit decision is an independent mutation. Only its subsequent
    // display refresh shares the selection's cancellation lifetime.
    await saveFindingFeedback(repository.id, finding.fingerprint, payload, session.access_token);
    if (!detailRequestIsCurrent(controller)) return;
    const refresh = ++detailRefresh.current;
    try {
      const detail = await fetchProjectDetail(repository.id, session.access_token, { signal: controller.signal });
      if (detailRequestIsCurrent(controller) && refresh === detailRefresh.current) setProjectDetail(detail);
    } catch (error) {
      if (detailRequestIsCurrent(controller) && refresh === detailRefresh.current) {
        setHistoryError(error.message);
      }
    }
  };

  const resetHistory = () => {
    listRequest.current?.abort();
    listRequest.current = null;
    detailRequest.current?.abort();
    detailRequest.current = null;
    setRepositories([]); setSelectedRepository(null); setProjectDetail(null);
    setIsHistoryLoading(false); setHistoryError("");
  };
  return { repositories, selectedRepository, projectDetail, isHistoryLoading, historyError,
    loadProjectList, openProjectDetail, updateFeedback, resetHistory };
}
