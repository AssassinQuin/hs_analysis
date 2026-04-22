"""analysis.watcher — Real-time Power.log monitoring and decision loop.

Architecture:
    LogWatcher (file tail) → GameTracker (incremental parse)
        → StateBridge (Entity → GameState) → RHEAEngine.search → output

Usage:
    from analysis.watcher import DecisionLoop

    loop = DecisionLoop("/path/to/Hearthstone/Logs/Power.log")
    loop.run()  # blocking, outputs decisions to stdout
"""
