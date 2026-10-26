"""Pub/Sub event bus: telematics, driver app, TMW and traffic feeds -> agent.

Producers publish one JSON message per event to PUBSUB_TOPIC, shaped like a
``route_events`` row (see db/schema.py). The worker stores each event and
asks the coordinator agent to handle it, so Gemini produces the dispatcher
explanation and the escalation decision on top of the deterministic re-plan.

  python -m route_optimizer.event_bus publish --file scripts/sample_events/breakdown.json
  python -m route_optimizer.event_bus worker            # LLM-in-the-loop
  python -m route_optimizer.event_bus worker --no-llm   # tool only, no Gemini call
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from .config import get_settings
from .db.repository import get_repository
from .db.schema import TABLES_BY_NAME

log = logging.getLogger("event_bus")
EVENT_COLUMNS = TABLES_BY_NAME["route_events"].column_names


def normalize_event(raw: dict) -> dict:
  missing = [k for k in ("event_id", "dc_id", "event_date", "event_min", "event_type") if raw.get(k) in (None, "")]
  if missing:
    raise ValueError(f"Event is missing {missing}")
  return {c: raw.get(c) for c in EVENT_COLUMNS}


def publish(event: dict) -> str:
  from google.cloud import pubsub_v1

  s = get_settings()
  publisher = pubsub_v1.PublisherClient()
  topic = publisher.topic_path(s.bq_project, s.pubsub_topic)
  data = json.dumps(normalize_event(event)).encode()
  return publisher.publish(topic, data, event_type=event["event_type"], dc_id=event["dc_id"]).result()


async def _agent_handle(event: dict) -> str:
  from google.adk.runners import InMemoryRunner
  from google.genai import types

  from .agent import root_agent

  runner = InMemoryRunner(agent=root_agent, app_name="mclane_route_events")
  session = await runner.session_service.create_session(app_name="mclane_route_events", user_id="event-bus")
  prompt = (
      f"New operational event {event['event_id']} ({event['event_type']}) at {event['dc_id']} on {event['event_date']}: "
      f"{event.get('description') or ''}. Handle it end to end and tell the dispatcher what changed and whether "
      "approval is needed."
  )
  text = []
  async for ev in runner.run_async(
      user_id="event-bus", session_id=session.id, new_message=types.Content(role="user", parts=[types.Part(text=prompt)])
  ):
    if ev.content and ev.content.parts and ev.is_final_response():
      text += [p.text for p in ev.content.parts if p.text]
  return "\n".join(text)


def process(event: dict, use_llm: bool = True) -> dict:
  """Stores an event and handles it. Returns the agent's answer or the tool result."""
  event = normalize_event(event)
  repo = get_repository()
  if not repo.query("SELECT event_id FROM route_events WHERE event_id = :e", {"e": event["event_id"]}):
    repo.insert("route_events", [event])
  if use_llm:
    return {"event_id": event["event_id"], "agent_response": asyncio.run(_agent_handle(event))}
  from .tools.event_tools import _handle

  return _handle(event)


def worker(use_llm: bool):
  from google.cloud import pubsub_v1

  s = get_settings()
  subscriber = pubsub_v1.SubscriberClient()
  path = subscriber.subscription_path(s.bq_project, s.pubsub_subscription)

  def callback(message):
    try:
      out = process(json.loads(message.data), use_llm)
      log.info("Handled %s: %s", out.get("event_id"), json.dumps(out, default=str)[:600])
      message.ack()
    except Exception:  # keep the subscriber alive; Pub/Sub redelivers on nack
      log.exception("Event failed")
      message.nack()

  log.info("Listening on %s", path)
  future = subscriber.subscribe(path, callback=callback, flow_control=pubsub_v1.types.FlowControl(max_messages=4))
  with subscriber:
    future.result()


def main(argv=None):
  logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  sub = ap.add_subparsers(dest="cmd", required=True)
  p = sub.add_parser("publish", help="Publish an event JSON file to Pub/Sub")
  p.add_argument("--file", required=True)
  w = sub.add_parser("worker", help="Consume events from Pub/Sub and handle them")
  w.add_argument("--no-llm", action="store_true")
  l = sub.add_parser("local", help="Handle an event JSON file locally without Pub/Sub")
  l.add_argument("--file", required=True)
  l.add_argument("--no-llm", action="store_true")
  args = ap.parse_args(argv)

  if args.cmd == "publish":
    print(publish(json.loads(Path(args.file).read_text())))
  elif args.cmd == "worker":
    worker(not args.no_llm)
  else:
    out = process(json.loads(Path(args.file).read_text()), not args.no_llm)
    json.dump(out, sys.stdout, indent=2, default=str)
    print()


if __name__ == "__main__":
  main()
