"use client";

import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { FormEvent, KeyboardEvent, useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  apiBaseUrl,
  apiRequest,
  ChatMessage,
  Conversation,
  ConversationList,
  MessageList,
} from "@/lib/api";
import { consumeSseFrames, ServerSentEvent } from "@/lib/sse";

type DisplayMessage = ChatMessage & { pending?: boolean };
type RetryTurn = { content: string; key: string; localUserId: string };
type StreamPayload = {
  turn_id?: string;
  delta?: string;
  replayed?: boolean;
  user_message?: ChatMessage;
  assistant_message?: ChatMessage;
  error?: { code?: string; message?: string };
};

const API_BASE = apiBaseUrl();

function messageFromOptimistic(
  id: string,
  conversationId: string,
  role: "user" | "assistant",
  content: string,
  pending = false,
): DisplayMessage {
  return {
    id,
    conversation_id: conversationId,
    turn_id: id,
    role,
    content,
    created_at: new Date().toISOString(),
    pending,
  };
}

export default function ChatWorkspace() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [hasMoreConversations, setHasMoreConversations] = useState(false);
  const [showArchived, setShowArchived] = useState(false);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retryTurn, setRetryTurn] = useState<RetryTurn | null>(null);
  const [hasOlderMessages, setHasOlderMessages] = useState(false);
  const [editingConversationId, setEditingConversationId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);
  const [providerLabel, setProviderLabel] = useState("Checking AI provider");
  const [historyOpen, setHistoryOpen] = useState(false);
  const abortControllerRef = useRef<AbortController | null>(null);
  const messageListRef = useRef<HTMLDivElement>(null);
  const conversationLoadRef = useRef(0);

  const loadConversations = useCallback(async () => {
    setLoadingHistory(true);
    try {
      const result = await apiRequest<ConversationList>(
        `/conversations?include_archived=${showArchived}&limit=100`,
      );
      setConversations(result.items);
      setHasMoreConversations(result.total > result.items.length);
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Could not load conversations.");
    } finally {
      setLoadingHistory(false);
    }
  }, [showArchived]);

  async function loadMoreConversations() {
    try {
      const result = await apiRequest<ConversationList>(
        `/conversations?include_archived=${showArchived}&limit=100&offset=${conversations.length}`,
      );
      setConversations((current) => [...current, ...result.items]);
      setHasMoreConversations(result.offset + result.items.length < result.total);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Could not load more conversations.");
    }
  }

  useEffect(() => {
    void loadConversations();
    void apiRequest<{
      provider: string;
      model: string;
      available: boolean;
    }>("/chat/provider")
      .then((result) =>
        setProviderLabel(
          `${result.provider} · ${result.model}${result.available ? "" : " · offline"}`,
        ),
      )
      .catch(() => setProviderLabel("AI provider unavailable"));
  }, [loadConversations]);

  useEffect(() => {
    const list = messageListRef.current;
    if (list) {
      list.scrollTop = list.scrollHeight;
    }
  }, [messages]);

  const openConversation = useCallback(async (conversationId: string) => {
    if (abortControllerRef.current) {
      const currentController = abortControllerRef.current;
      abortControllerRef.current = null;
      currentController.abort();
    }
    const loadId = ++conversationLoadRef.current;
    setHistoryOpen(false);
    setActiveConversationId(conversationId);
    setMessages([]);
    setError(null);
    setRetryTurn(null);
    setIsStreaming(false);
    setLoadingMessages(true);
    try {
      const result = await apiRequest<MessageList>(
        `/conversations/${conversationId}/messages?limit=100&offset=0`,
      );
      if (conversationLoadRef.current !== loadId) {
        return;
      }
      setMessages(result.items);
      setHasOlderMessages(result.has_more);
    } catch (loadError) {
      if (conversationLoadRef.current === loadId) {
        setError(loadError instanceof Error ? loadError.message : "Could not load messages.");
      }
    } finally {
      if (conversationLoadRef.current === loadId) {
        setLoadingMessages(false);
      }
    }
  }, []);

  async function createConversation(): Promise<Conversation> {
    setShowArchived(false);
    setHistoryOpen(false);
    const conversation = await apiRequest<Conversation>("/conversations", {
      method: "POST",
      body: JSON.stringify({}),
    });
    setConversations((current) => [
      conversation,
      ...current.filter((item) => item.id !== conversation.id),
    ]);
    setActiveConversationId(conversation.id);
    setMessages([]);
    setError(null);
    setRetryTurn(null);
    setHasOlderMessages(false);
    return conversation;
  }

  async function startNewConversation() {
    if (abortControllerRef.current) {
      const currentController = abortControllerRef.current;
      abortControllerRef.current = null;
      currentController.abort();
    }
    try {
      await createConversation();
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : "Could not start a conversation.");
    }
  }

  function applyStreamEvent(
    event: ServerSentEvent,
    conversationId: string,
    assistantPlaceholderId: string,
    localUserId: string,
  ): "done" | string | undefined {
    let payload: StreamPayload;
    try {
      payload = JSON.parse(event.data) as StreamPayload;
    } catch {
      return "The chat stream returned invalid data.";
    }

    if (event.event === "meta" && payload.user_message) {
      setMessages((current) => {
        const userIndex = current.findIndex((message) => message.id === localUserId);
        const result = [...current];
        if (userIndex >= 0) {
          result[userIndex] = payload.user_message!;
        } else if (!result.some((message) => message.id === payload.user_message!.id)) {
          result.push(payload.user_message!);
        }
        const assistantIndex = result.findIndex(
          (message) => message.id === assistantPlaceholderId,
        );
        if (assistantIndex >= 0) {
          result[assistantIndex] = {
            ...result[assistantIndex],
            content: "",
            pending: true,
          };
        } else {
          result.push(
            messageFromOptimistic(
              assistantPlaceholderId,
              conversationId,
              "assistant",
              "",
              true,
            ),
          );
        }
        return result;
      });
    } else if (event.event === "delta" && payload.delta) {
      setMessages((current) =>
        current.map((message) =>
          message.id === assistantPlaceholderId
            ? { ...message, content: message.content + payload.delta }
            : message,
        ),
      );
    } else if (event.event === "done" && payload.assistant_message) {
      setMessages((current) =>
        current.map((message) =>
          message.id === assistantPlaceholderId
            ? payload.assistant_message!
            : message,
        ),
      );
      setRetryTurn(null);
      setError(null);
      void loadConversations();
      return "done";
    } else if (event.event === "error") {
      setMessages((current) =>
        current.map((message) =>
          message.id === assistantPlaceholderId
            ? { ...message, pending: false }
            : message,
        ),
      );
      return payload.error?.message ?? "The AI provider could not complete the request.";
    }
    return undefined;
  }

  async function sendTurn(content: string, retry?: RetryTurn) {
    const conversation =
      conversations.find((item) => item.id === activeConversationId) ??
      (activeConversationId ? { id: activeConversationId } : await createConversation());
    const conversationId = conversation.id;
    const key = retry?.key ?? crypto.randomUUID();
    const localUserId = retry?.localUserId ?? `local-user-${key}`;
    const assistantPlaceholderId = `local-assistant-${key}`;

    if (!retry) {
      setMessages((current) => [
        ...current,
        messageFromOptimistic(localUserId, conversationId, "user", content),
        messageFromOptimistic(
          assistantPlaceholderId,
          conversationId,
          "assistant",
          "",
          true,
        ),
      ]);
    } else {
      setMessages((current) => {
        const hasAssistant = current.some((message) => message.id === assistantPlaceholderId);
        if (hasAssistant) {
          return current.map((message) =>
            message.id === assistantPlaceholderId
              ? { ...message, content: "", pending: true }
              : message,
          );
        }
        return [
          ...current,
          messageFromOptimistic(
            assistantPlaceholderId,
            conversationId,
            "assistant",
            "",
            true,
          ),
        ];
      });
    }

    setIsStreaming(true);
    setError(null);
    const controller = new AbortController();
    abortControllerRef.current = controller;
    let finished = false;
    let reader: ReadableStreamDefaultReader<Uint8Array> | null = null;
    try {
      const response = await fetch(
        `${API_BASE}/conversations/${conversationId}/messages/stream`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": key,
          },
          body: JSON.stringify({ content }),
          signal: controller.signal,
          cache: "no-store",
        },
      );
      if (!response.ok) {
        const body = (await response.json().catch(() => ({}))) as {
          error?: { message?: string };
        };
        throw new ApiError(
          body.error?.message ?? `Request failed with status ${response.status}.`,
          response.status,
          "request_failed",
        );
      }
      if (!response.body) {
        throw new Error("The browser could not read the chat stream.");
      }
      reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      const process = (events: ServerSentEvent[]) => {
        for (const event of events) {
          const result = applyStreamEvent(
            event,
            conversationId,
            assistantPlaceholderId,
            localUserId,
          );
          if (result === "done") {
            finished = true;
          } else if (result) {
            throw new Error(result);
          }
        }
      };

      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          buffer += decoder.decode();
          const final = consumeSseFrames(buffer, true);
          process(final.events);
          break;
        }
        buffer += decoder.decode(value, { stream: true });
        const parsed = consumeSseFrames(buffer);
        buffer = parsed.remainder;
        process(parsed.events);
      }
      if (!finished) {
        throw new Error("The chat stream ended before a response was saved.");
      }
    } catch (streamError) {
      if (abortControllerRef.current !== controller) {
        return;
      }
      const message =
        controller.signal.aborted
          ? "Response stopped. Retry to continue this turn."
          : streamError instanceof Error
            ? streamError.message
            : "The response could not be completed.";
      setError(message);
      setRetryTurn({ content, key, localUserId });
      setMessages((current) =>
        current.filter((item) => item.id !== assistantPlaceholderId || item.content.length > 0),
      );
      if (!retry) {
        setMessages((current) =>
          current.some((item) => item.id === localUserId)
            ? current
            : [...current, messageFromOptimistic(localUserId, conversationId, "user", content)],
        );
      }
    } finally {
      reader?.releaseLock();
      if (abortControllerRef.current === controller) {
        abortControllerRef.current = null;
        setIsStreaming(false);
      } else if (abortControllerRef.current === null && controller.signal.aborted) {
        setIsStreaming(false);
      }
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const content = draft.trim();
    if (!content || isStreaming) {
      return;
    }
    setDraft("");
    await sendTurn(content);
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  }

  async function retryResponse() {
    if (!retryTurn || isStreaming) {
      return;
    }
    const retry = retryTurn;
    setRetryTurn(null);
    await sendTurn(retry.content, retry);
  }

  async function loadOlderMessages() {
    if (!activeConversationId || loadingMessages) {
      return;
    }
    setLoadingMessages(true);
    try {
      const offset = messages.length;
      const result = await apiRequest<MessageList>(
        `/conversations/${activeConversationId}/messages?limit=100&offset=${offset}`,
      );
      setMessages((current) => [...result.items, ...current]);
      setHasOlderMessages(result.has_more);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Could not load older messages.");
    } finally {
      setLoadingMessages(false);
    }
  }

  async function saveConversationTitle(conversationId: string) {
    try {
      const updated = await apiRequest<Conversation>(`/conversations/${conversationId}`, {
        method: "PATCH",
        body: JSON.stringify({ title: editingTitle }),
      });
      setConversations((current) =>
        current.map((conversation) =>
          conversation.id === conversationId ? updated : conversation,
        ),
      );
      setEditingConversationId(null);
      setError(null);
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Could not rename conversation.");
    }
  }

  async function toggleArchiveConversation(conversationId: string) {
    const conversation = conversations.find((item) => item.id === conversationId);
    if (!conversation) {
      return;
    }
    const archived = !conversation.archived;
    try {
      const updated = await apiRequest<Conversation>(`/conversations/${conversationId}`, {
        method: "PATCH",
        body: JSON.stringify({ archived }),
      });
      if (archived && !showArchived) {
        setConversations((current) => current.filter((item) => item.id !== conversationId));
      } else {
        setConversations((current) =>
          current.map((item) => (item.id === conversationId ? updated : item)),
        );
      }
      if (archived && activeConversationId === conversationId) {
        setActiveConversationId(null);
        setMessages([]);
      }
    } catch (archiveError) {
      setError(archiveError instanceof Error ? archiveError.message : "Could not archive conversation.");
    }
  }

  async function deleteConversation(conversationId: string) {
    if (!window.confirm("Delete this conversation and its messages permanently?")) {
      return;
    }
    try {
      await apiRequest<void>(`/conversations/${conversationId}`, { method: "DELETE" });
      setConversations((current) => current.filter((item) => item.id !== conversationId));
      if (activeConversationId === conversationId) {
        setActiveConversationId(null);
        setMessages([]);
      }
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : "Could not delete conversation.");
    }
  }

  async function copyMessage(message: DisplayMessage) {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopiedMessageId(message.id);
      window.setTimeout(() => setCopiedMessageId(null), 1500);
    } catch {
      setError("Could not copy the response to the clipboard.");
    }
  }

  const activeConversation = conversations.find(
    (conversation) => conversation.id === activeConversationId,
  );
  const canSend =
    draft.trim().length > 0 && !isStreaming && activeConversation?.archived !== true;

  return (
    <main className={`chat-shell ${historyOpen ? "history-open" : ""}`}>
      <aside className="chat-sidebar">
        <Link className="brand chat-brand" href="/" aria-label="Metamorphosis dashboard">
          <span className="brand-mark">M</span>
          <span>metamorphosis</span>
        </Link>
        <div className="chat-sidebar-heading">
          <span>YOUR WORKSPACE</span>
          <Link href="/" aria-label="Back to dashboard" title="Back to dashboard">⌂</Link>
        </div>
        <button className="new-chat-button" type="button" onClick={startNewConversation}>
          <span>＋</span> New conversation
        </button>
        <div className="chat-history-heading">
          <span>{showArchived ? "ARCHIVED CONVERSATIONS" : "RECENT CONVERSATIONS"}</span>
          <button
            type="button"
            aria-pressed={showArchived}
            onClick={() => setShowArchived((current) => !current)}
          >
            {showArchived ? "Recent" : "Archived"}
          </button>
        </div>
        <div className="conversation-list">
          {loadingHistory && conversations.length === 0 && (
            <p className="history-state">Loading conversations…</p>
          )}
          {!loadingHistory && conversations.length === 0 && (
            <p className="history-state">Your conversations will appear here.</p>
          )}
          {conversations.map((conversation) => (
            <div
              className={`conversation-row ${activeConversationId === conversation.id ? "selected" : ""}`}
              key={conversation.id}
            >
              {editingConversationId === conversation.id ? (
                <form
                  className="rename-form"
                  onSubmit={(event) => {
                    event.preventDefault();
                    void saveConversationTitle(conversation.id);
                  }}
                >
                  <input
                    aria-label="Conversation title"
                    maxLength={120}
                    value={editingTitle}
                    onChange={(event) => setEditingTitle(event.target.value)}
                    autoFocus
                  />
                  <button type="submit" aria-label="Save conversation title">✓</button>
                </form>
              ) : (
                <>
                  <button
                    className="conversation-select"
                    type="button"
                    onClick={() => void openConversation(conversation.id)}
                    aria-current={activeConversationId === conversation.id ? "page" : undefined}
                  >
                    <span className="conversation-icon">◷</span>
                    <span className="conversation-title">{conversation.title}</span>
                  </button>
                  <div className="conversation-actions">
                    <button
                      type="button"
                      aria-label={`Rename ${conversation.title}`}
                      title="Rename"
                      onClick={() => {
                        setEditingConversationId(conversation.id);
                        setEditingTitle(conversation.title);
                      }}
                    >
                      ✎
                    </button>
                    <button
                      type="button"
                      aria-label={`${conversation.archived ? "Restore" : "Archive"} ${conversation.title}`}
                      title={conversation.archived ? "Restore" : "Archive"}
                      onClick={() => void toggleArchiveConversation(conversation.id)}
                    >
                      {conversation.archived ? "↶" : "▱"}
                    </button>
                    <button
                      type="button"
                      aria-label={`Delete ${conversation.title}`}
                      title="Delete"
                      onClick={() => void deleteConversation(conversation.id)}
                    >
                      ×
                    </button>
                  </div>
                </>
              )}
            </div>
          ))}
          {hasMoreConversations && (
            <button
              className="load-conversations-button"
              type="button"
              onClick={() => void loadMoreConversations()}
            >
              Load more conversations
            </button>
          )}
        </div>
        <div className="chat-profile">
          <span className="avatar">B</span>
          <span><strong>Local development</strong><small>Personal workspace</small></span>
        </div>
      </aside>

      {historyOpen && (
        <button
          className="history-backdrop"
          type="button"
          aria-label="Close conversation history"
          onClick={() => setHistoryOpen(false)}
        />
      )}

      <section className="chat-main">
        <header className="chat-topbar">
          <button
            className="mobile-history-toggle"
            type="button"
            aria-expanded={historyOpen}
            onClick={() => setHistoryOpen((current) => !current)}
          >
            {historyOpen ? "Close" : "History"}
          </button>
          <div className="chat-breadcrumb">
            <Link href="/">Workspace</Link><span>/</span><strong>AI assistant</strong>
          </div>
          <div className="chat-provider-badge">
            <span className="provider-dot" />
            <span>{providerLabel}</span>
          </div>
        </header>

        <div className="chat-conversation-heading">
          <div>
            <p className="eyebrow">METAMORPHOSIS ASSISTANT</p>
            <h1>{activeConversation?.title ?? "AI assistant"}</h1>
          </div>
          <span className="chat-local-tag">LOCAL CHAT</span>
        </div>

        <div className="chat-messages" ref={messageListRef} aria-live="polite">
          {hasOlderMessages && activeConversationId && (
            <button
              className="load-older-button"
              type="button"
              disabled={loadingMessages}
              onClick={() => void loadOlderMessages()}
            >
              Load older messages
            </button>
          )}
          {loadingMessages && messages.length === 0 && (
            <div className="chat-loading"><span className="typing-indicator" /> Loading messages…</div>
          )}
          {messages.length === 0 && !loadingMessages && (
            <div className="chat-empty-state">
              <span className="chat-empty-mark">✳</span>
              <h2>What would you like to work on?</h2>
              <p>Ask a question, explore an idea, or get help turning a task into clear next steps.</p>
              <div className="suggestion-row">
                <button type="button" onClick={() => setDraft("Help me plan a simple workflow.")}>
                  Plan a workflow
                </button>
                <button type="button" onClick={() => setDraft("Explain a topic in simple terms.")}>
                  Explain a topic
                </button>
              </div>
            </div>
          )}
          {messages.map((message) => (
            <article
              className={`message-row message-${message.role}`}
              key={message.id}
              aria-label={`${message.role} message`}
            >
              <div className={`message-avatar ${message.role === "assistant" ? "assistant-avatar" : ""}`}>
                {message.role === "assistant" ? "✳" : "B"}
              </div>
              <div className="message-content">
                <div className="message-meta">
                  <strong>{message.role === "assistant" ? "Metamorphosis" : "You"}</strong>
                  {message.pending && message.content.length === 0 && (
                    <span className="typing-indicator" aria-label="Assistant is responding" />
                  )}
                  {message.pending && message.content.length > 0 && (
                    <span className="streaming-label">responding…</span>
                  )}
                </div>
                {message.role === "assistant" && message.content ? (
                  <div className="markdown-body">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {message.content}
                    </ReactMarkdown>
                  </div>
                ) : message.content ? (
                  <p className="user-message-text">{message.content}</p>
                ) : message.pending ? null : (
                  <p className="user-message-text">{message.content}</p>
                )}
                {message.role === "assistant" && message.content && !message.pending && (
                  <button
                    className="copy-message-button"
                    type="button"
                    onClick={() => void copyMessage(message)}
                    aria-label="Copy response"
                  >
                    {copiedMessageId === message.id ? "Copied" : "Copy"}
                  </button>
                )}
              </div>
            </article>
          ))}
          {error && (
            <div className="chat-error" role="alert">
              <span>{error}</span>
              {retryTurn && (
                <button type="button" onClick={() => void retryResponse()} disabled={isStreaming}>
                  Retry response
                </button>
              )}
            </div>
          )}
        </div>

        <div className="composer-wrap">
          <form className="chat-composer" onSubmit={(event) => void handleSubmit(event)}>
            <label className="sr-only" htmlFor="chat-prompt">Message the assistant</label>
            <textarea
              id="chat-prompt"
              value={draft}
              maxLength={20_000}
              rows={1}
              placeholder="Message Metamorphosis…"
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={handleComposerKeyDown}
              disabled={isStreaming || activeConversation?.archived === true}
            />
            {isStreaming ? (
              <button
                className="send-button stop-button"
                type="button"
                aria-label="Stop response"
                onClick={() => abortControllerRef.current?.abort()}
              >
                ■
              </button>
            ) : (
              <button
                className="send-button"
                type="submit"
                disabled={!canSend}
                aria-label="Send message"
              >
                ↑
              </button>
            )}
          </form>
          <p className="composer-hint">
            Enter to send · Shift + Enter for a new line · Replies use the selected AI provider
          </p>
        </div>
      </section>
    </main>
  );
}
