import asyncio

async def inner_gen():
    yield "a"
    yield "b"

async def outer_gen():
    try:
        async for item in inner_gen():
            yield item
        while True:
            try:
                await asyncio.wait_for(asyncio.Event().wait(), timeout=0.1)
            except asyncio.TimeoutError:
                pass
            except asyncio.CancelledError:
                return
    finally:
        print("FINALLY ran")

async def main():
    collected = []
    async for item in outer_gen():
        collected.append(item)
        print(f"Got: {item}")
        if len(collected) >= 2:
            break
    print(f"Breaking with {collected}")
    print("Done")

asyncio.run(main())
