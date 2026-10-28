async def test_generated_derivatives_and_partial_files_are_accounted_for(services, video_asset):
    config, store, media, _, _ = services
    from tg_netdisk.models.schemas import Draft, DraftItem

    await store.save("drafts", Draft(items=[DraftItem(media_id=video_asset["id"])]).model_dump())
    protected = config.data_dir / "cache/thumbnails" / f"{video_asset['id']}-photo.jpg"
    orphan = config.data_dir / "cache/thumbnails" / "unused-cover.jpg"
    partial = config.data_dir / "cache/downloads" / "interrupted.part"
    protected.write_bytes(b"keep")
    orphan.write_bytes(b"remove")
    partial.write_bytes(b"partial")
    stats = await media.cache()
    assert stats["protected"] == 4
    assert stats["reclaimable"] == 13
    cleaned = await media.cache(True)
    assert cleaned["removed"] == 13
    assert protected.exists() and not orphan.exists() and not partial.exists()
