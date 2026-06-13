#!/usr/bin/env python3
"""
AI Job Application Agent — CLI Entry Point

Run the autonomous AI agent that applies for jobs on your behalf.

Usage:
    # Run once on Naukri
    python3 run_agent.py --platform naukri --target 20

    # Run once on LinkedIn
    python3 run_agent.py --platform linkedin --target 15

    # Run as daemon (24/7)
    python3 run_agent.py --daemon

    # Review mode (queue jobs, don't auto-apply)
    python3 run_agent.py --platform naukri --review-only

    # Dry run (analyze but don't submit)
    python3 run_agent.py --platform naukri --dry-run

    # Check agent status
    python3 run_agent.py --status

    # Check Ollama setup
    python3 run_agent.py --check
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))


def _log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")


def cmd_check():
    """Check if Ollama and model are ready."""
    from ai_agent.llm_client import LLMClient
    from ai_agent.agent import load_agent_config

    config = load_agent_config()
    model = config.get("agent_ollama_model", "qwen3:8b")
    url = config.get("agent_ollama_url", "http://localhost:11434")

    print("=" * 60)
    print("AI Agent Setup Check")
    print("=" * 60)

    client = LLMClient(model=model, base_url=url)

    # Check Ollama
    print(f"\n1. Ollama Server ({url}):")
    if client.ping():
        print("   ✅ Connected")
    else:
        print("   ❌ Not running!")
        print("   → Install: https://ollama.com/download")
        print("   → Start:   ollama serve")
        return False

    # Check model
    print(f"\n2. Model ({model}):")
    if client.is_model_available():
        print("   ✅ Available")
    else:
        print(f"   ❌ Not found. Pulling...")
        try:
            client.ensure_model()
            print("   ✅ Pulled successfully")
        except Exception as e:
            print(f"   ❌ Failed: {e}")
            print(f"   → Run manually: ollama pull {model}")
            return False

    # Quick test
    print("\n3. Quick Test:")
    try:
        response = client.ask("Say 'ready' in one word.", temperature=0.0)
        print(f"   ✅ LLM responded: {response[:50]}")
    except Exception as e:
        print(f"   ❌ Test failed: {e}")
        return False

    # Check resume
    print("\n4. Resume:")
    resume_path = config.get("resume_path", "")
    if resume_path and Path(resume_path).exists():
        print(f"   ✅ Found: {Path(resume_path).name}")
        try:
            from resume_parser import parse_resume
            data = parse_resume(resume_path)
            print(f"   → Name: {data.get('full_name', 'Unknown')}")
            print(f"   → Skills: {data.get('skills_text', '')[:60]}")
            print(f"   → Experience: {data.get('experience_years', '?')} years")
        except Exception as e:
            print(f"   ⚠ Could not parse: {e}")
    else:
        print("   ⚠ Not configured (set resume_path in config.json)")

    print("\n" + "=" * 60)
    print("✅ AI Agent is ready to run!")
    print("=" * 60)
    return True


def cmd_status():
    """Show agent stats from memory."""
    from ai_agent.agent_memory import AgentMemory

    memory = AgentMemory()
    stats = memory.get_stats()

    print("\n" + "=" * 60)
    print("AI Agent Status")
    print("=" * 60)

    print(f"\n📊 Overall Stats:")
    print(f"   Total Applied:   {stats['total_applied']}")
    print(f"   Today Applied:   {stats['today_applied']}")
    print(f"   Total Skipped:   {stats['total_skipped']}")
    print(f"   Total Analyzed:  {stats['total_analyzed']}")
    print(f"   Avg Match Score: {stats['avg_match_score']}%")
    print(f"   Pending Reviews: {stats['pending_reviews']}")

    if stats["by_platform"]:
        print(f"\n📋 By Platform:")
        for platform, count in stats["by_platform"].items():
            print(f"   {platform}: {count}")

    if stats["last_run"]:
        lr = stats["last_run"]
        print(f"\n🕐 Last Run:")
        print(f"   Platform: {lr.get('platform', '?')}")
        print(f"   Started:  {lr.get('start_time', '?')}")
        print(f"   Status:   {lr.get('status', '?')}")
        print(f"   Applied:  {lr.get('jobs_applied', 0)}")
        print(f"   Skipped:  {lr.get('jobs_skipped', 0)}")

    # Recent decisions
    decisions = memory.get_decisions(limit=5)
    if decisions:
        print(f"\n🧠 Recent AI Decisions:")
        for d in decisions:
            emoji = "✅" if d["decision"] == "APPLY" else "⏭" if d["decision"] == "SKIP" else "👀"
            print(f"   {emoji} [{d['match_score']:.0f}%] {d['company']} — {d['job_title'][:30]}")
            if d["reasoning"]:
                print(f"      → {d['reasoning'][:80]}")

    print()


def cmd_run(args):
    """Run the agent."""
    from ai_agent.agent import JobApplicationAgent, load_agent_config

    config = load_agent_config()

    # Override with CLI args
    if args.model:
        config["agent_ollama_model"] = args.model
    if args.review_only:
        config["agent_mode"] = "review"
    if args.min_score is not None:
        config["agent_min_match_score"] = args.min_score

    agent = JobApplicationAgent(config=config)

    if args.daemon:
        schedule = args.schedule.split(",") if args.schedule else None
        agent.run_daemon(schedule_times=schedule, headless=not args.headed)
    else:
        agent.run_cycle(
            platform=args.platform,
            target=args.target,
            headless=not args.headed,
            dry_run=args.dry_run,
        )


def cmd_decisions(args):
    """View AI decisions log."""
    from ai_agent.agent_memory import AgentMemory

    memory = AgentMemory()
    decisions = memory.get_decisions(limit=args.limit, platform=args.platform or "")

    if not decisions:
        print("No decisions recorded yet.")
        return

    print(f"\n{'Decision':<8} {'Score':<7} {'Company':<20} {'Title':<30} {'Time'}")
    print("-" * 100)

    for d in decisions:
        emoji = "✅" if d["decision"] == "APPLY" else "⏭" if d["decision"] == "SKIP" else "👀"
        ts = d["created_at"][:16] if d["created_at"] else "?"
        print(f"{emoji} {d['decision']:<6} {d['match_score']:>5.0f}%  {d['company'][:18]:<20} {d['job_title'][:28]:<30} {ts}")
        if args.verbose and d["reasoning"]:
            print(f"         → {d['reasoning'][:100]}")


def cmd_queue(args):
    """View or manage review queue."""
    from ai_agent.agent_memory import AgentMemory

    memory = AgentMemory()
    queue = memory.get_review_queue(status="pending")

    if not queue:
        print("Review queue is empty.")
        return

    print(f"\n📋 Pending Review ({len(queue)} jobs)")
    print("-" * 80)

    for item in queue:
        print(f"\n  [{item['id']}] {item['company']} — {item['job_title']}")
        print(f"      Score: {item['match_score']:.0f}% | Platform: {item['platform']}")
        print(f"      Reason: {item['reasoning'][:80]}")
        print(f"      URL: {item['job_url'][:60]}")

    print(f"\n  To approve: python3 run_agent.py queue --approve <id>")
    print(f"  To reject:  python3 run_agent.py queue --reject <id>")

    if args.approve:
        memory.approve_review(args.approve)
        print(f"\n✅ Approved item #{args.approve}")

    if args.reject:
        memory.reject_review(args.reject)
        print(f"\n❌ Rejected item #{args.reject}")


def main():
    parser = argparse.ArgumentParser(
        description="🤖 AI Job Application Agent — Apply for jobs autonomously using local LLM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 run_agent.py --check                           Check Ollama setup
  python3 run_agent.py --platform naukri --target 20     Apply to 20 Naukri jobs
  python3 run_agent.py --platform linkedin --dry-run     Analyze LinkedIn jobs without applying
  python3 run_agent.py --daemon                          Run 24/7 on schedule
  python3 run_agent.py --status                          View stats
  python3 run_agent.py decisions                         View AI decision log
  python3 run_agent.py queue                             Manage review queue
""",
    )

    parser.add_argument("--check", action="store_true", help="Check Ollama and model setup")
    parser.add_argument("--status", action="store_true", help="Show agent stats")
    parser.add_argument("--platform", choices=["naukri", "linkedin"], default="naukri",
                        help="Job platform to use (default: naukri)")
    parser.add_argument("--target", type=int, default=20, help="Number of jobs to apply to (default: 20)")
    parser.add_argument("--headed", action="store_true", help="Run browser in visible mode (not headless)")
    parser.add_argument("--dry-run", action="store_true", help="Analyze jobs but don't submit applications")
    parser.add_argument("--review-only", action="store_true", help="Queue jobs for review instead of auto-applying")
    parser.add_argument("--daemon", action="store_true", help="Run as 24/7 daemon on schedule")
    parser.add_argument("--schedule", type=str, help="Comma-separated schedule times for daemon (e.g., '09:00,14:00,20:00')")
    parser.add_argument("--model", type=str, help="Override Ollama model (e.g., 'qwen3:14b')")
    parser.add_argument("--min-score", type=int, help="Minimum match score to apply (default: 60)")

    subparsers = parser.add_subparsers(dest="command")

    # decisions subcommand
    dec_parser = subparsers.add_parser("decisions", help="View AI decisions log")
    dec_parser.add_argument("--limit", type=int, default=20, help="Number of decisions to show")
    dec_parser.add_argument("--platform", type=str, help="Filter by platform")
    dec_parser.add_argument("-v", "--verbose", action="store_true", help="Show reasoning")

    # queue subcommand
    q_parser = subparsers.add_parser("queue", help="Manage review queue")
    q_parser.add_argument("--approve", type=int, help="Approve a queued job by ID")
    q_parser.add_argument("--reject", type=int, help="Reject a queued job by ID")

    args = parser.parse_args()

    if args.check:
        sys.exit(0 if cmd_check() else 1)
    elif args.status:
        cmd_status()
    elif args.command == "decisions":
        cmd_decisions(args)
    elif args.command == "queue":
        cmd_queue(args)
    else:
        cmd_run(args)


if __name__ == "__main__":
    main()
