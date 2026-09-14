"""`app.services.video_matching` — the chooser is pure, so every rule gets a case."""

from app.services.video import VideoSearchResult
from app.services.video_matching import (
    artist_tokens,
    choose,
    primary_artist,
    title_tokens,
)


def result(title, channel="SomeChannel", duration=240, video_id="v1", description=""):
    return VideoSearchResult(
        video_id=video_id, title=title, channel=channel, duration=duration,
        thumbnail_url="", url=f"https://www.youtube.com/watch?v={video_id}",
        description=description,
    )


def pick(results, *, title="Evil", artist="Interpol", duration=220):
    return choose(title=title, artist=artist, duration_seconds=duration, results=results)


class TestNaming:
    def test_the_plain_official_video_matches(self):
        v = pick([result("Interpol - Evil (Official Video)", "InterpolVEVO", 221)])
        assert v.matched
        assert v.reason.startswith("matched: official video")

    def test_artist_can_be_named_by_the_channel_alone(self):
        v = pick([result("Evil", "Interpol", 221)])
        assert v.matched

    def test_artist_runs_through_a_vevo_channel_without_spaces(self):
        v = pick([result("Bloodbuzz Ohio", "TheNationalVEVO", 275)],
                 title="Bloodbuzz Ohio", artist="The National", duration=276)
        assert v.matched

    def test_a_result_that_names_neither_is_refused(self):
        v = pick([result("Some Other Band - Evil", "OtherBand", 221)])
        assert not v.matched
        assert "does not name the artist" in v.reason

    def test_every_title_token_is_required(self):
        v = pick([result("Interpol - Evil Live Session", "InterpolVEVO", 221)],
                 title="Not Even Jail")
        assert not v.matched
        assert "does not name the title" in v.reason

    def test_title_noise_is_not_required(self):
        v = pick([result("The Cure - Just Like Heaven", "TheCureVEVO", 212)],
                 title="Just Like Heaven (2006 Remaster)", artist="The Cure", duration=210)
        assert v.matched

    def test_a_guest_artist_is_not_required(self):
        v = pick([result("Gorillaz - Feel Good Inc. (Official Video)", "Gorillaz", 222)],
                 title="Feel Good Inc.", artist="Gorillaz feat. De La Soul", duration=222)
        assert v.matched

    def test_accents_fold(self):
        v = pick([result("Sigur Ros - Agaetis Byrjun", "sigurros", 470)],
                 title="Ágætis Byrjun", artist="Sigur Rós", duration=471)
        assert v.matched


class TestWhatIsNotTheVideo:
    def test_live_is_refused(self):
        v = pick([result("Interpol - Evil (Live at Glastonbury)", "InterpolVEVO", 221)])
        assert not v.matched
        assert "says 'live'" in v.reason

    def test_official_audio_is_refused(self):
        v = pick([result("Interpol - Evil (Official Audio)", "InterpolVEVO", 221)])
        assert not v.matched
        assert "official audio" in v.reason

    def test_lyric_video_is_refused(self):
        v = pick([result("Interpol - Evil (Lyric Video)", "InterpolVEVO", 221)])
        assert not v.matched

    def test_a_word_in_the_tracks_own_title_is_exempt(self):
        v = pick([result("Skrillex - Bangarang Remix", "Skrillex", 215)],
                 title="Bangarang Remix", artist="Skrillex", duration=215)
        assert v.matched

    def test_an_art_track_is_refused_by_its_description(self):
        """The dry run's first fifteen "matches" were all of these: bare title, the artist's own
        channel, exactly the album length. Nothing but the description gives them away."""
        v = pick([result("Into The Magic Land", "Boards of Canada", 275,
                         description="Provided to YouTube by IIP-DDS\n\nInto The Magic Land · Boards of Canada")],
                 title="Into The Magic Land", artist="Boards of Canada", duration=275)
        assert not v.matched
        assert "art track" in v.reason

    def test_a_topic_channel_is_the_older_art_track(self):
        v = pick([result("Evil", "Interpol - Topic", 221)])
        assert not v.matched
        assert "art track" in v.reason

    def test_a_channel_that_merely_contains_the_name_is_not_the_artist(self):
        v = pick([result("Modest Mouse - Fire It Up", "Modest Mouse Man", 250)],
                 title="Fire It Up", artist="Modest Mouse", duration=250)
        assert not v.matched

    def test_conventional_channel_suffixes_are_the_artist(self):
        for channel in ("Pinback", "pinbackmusic", "PinbackVEVO", "Pinback Official", "The Pinback"):
            v = pick([result("Pinback - Good to Sea", channel, 250)],
                     title="Good to Sea", artist="Pinback", duration=250)
            assert v.matched, channel

    def test_an_unexplained_bracket_is_refused_even_on_the_artists_channel(self):
        for track, title in (
            ("Fire It Up", "Modest Mouse - Fire It Up (Pepsi Smash on Yahoo! Music 2007)"),
            ("Passenger", 'Interpol - "Passenger" (Fan Submission)'),
            ("Even Spring", "Plaid - Even Spring (alternate)"),
        ):
            v = pick([result(title, "Interpol", 221)], title=track, artist="Interpol", duration=221)
            assert not v.matched, title
            assert "bracket" in v.reason, v.reason

    def test_explained_brackets_pass(self):
        for title in (
            "Interpol - Evil (Official Video)",
            "Interpol - Evil [HD]",
            "Interpol - Evil (2012 Remaster)",
            "Interpol - Evil (feat. Nobody)",
            "Interpol - Evil (Official Video) [4K Upgrade]",
        ):
            v = pick([result(title, "InterpolVEVO", 221)])
            assert v.matched, title

    def test_a_strangers_bare_upload_is_refused(self):
        v = pick([result("Everything Is Wrong - Interpol", "Camilo 8", 221)],
                 title="Everything Is Wrong", artist="Interpol", duration=221)
        assert not v.matched
        assert "not called official" in v.reason

    def test_a_bare_audio_upload_on_the_artists_channel_is_refused(self):
        v = pick([result("M83 - Road Blaster (Audio)", "M83", 250)],
                 title="Road Blaster", artist="M83", duration=250)
        assert not v.matched
        assert "'audio'" in v.reason

    def test_official_in_a_channel_name_needs_the_artist_in_it_too(self):
        v = pick([result("Holy ghost wait and see (Music)", "MusicStationOfficial", 240)],
                 title="Wait And See", artist="Holy Ghost!", duration=240)
        assert not v.matched

    def test_a_performance_clip_is_refused(self):
        v = pick([result("Cyclical Cyclical situation performance #2 by pictureplane", "PICTUREPLANE", 250)],
                 title="Cyclical Cyclical", artist="Pictureplane", duration=240)
        assert not v.matched

    def test_music_video_alone_is_not_credible_from_a_stranger(self):
        v = pick([result("Boards of Canada - Left Side Drive (Music Video)", "Xavier LeBlanc", 300)],
                 title="Left Side Drive", artist="Boards of Canada", duration=300)
        assert not v.matched

    def test_a_strangers_upload_that_says_official_video_passes(self):
        """Labels and fans both title them that way; the duration and the reject words are what
        keep this honest, and a hand-picked match would have taken it too."""
        v = pick([result("Interpol - Evil (Official Video)", "randomuploader", 221)])
        assert v.matched

    def test_the_artists_own_channel_is_credible_without_the_word_official(self):
        v = pick([result("PDA (2012 Remaster)", "Interpol", 221)], title="PDA", duration=220)
        assert v.matched


class TestDuration:
    def test_a_full_album_fails_on_length_before_anything_else(self):
        v = pick([result("Interpol - Antics (Full Album) Evil", "Someone", 2500)])
        assert not v.matched

    def test_an_intro_and_outro_are_allowed(self):
        v = pick([result("Interpol - Evil (Official Video)", "InterpolVEVO", 261)], duration=220)
        assert v.matched  # 41s over, tolerance is max(30, 44)

    def test_too_long_is_refused(self):
        v = pick([result("Interpol - Evil (Official Video)", "InterpolVEVO", 300)], duration=220)
        assert not v.matched
        assert "80s off" in v.reason

    def test_without_a_track_duration_the_title_must_say_official(self):
        assert pick([result("Interpol - Evil", "InterpolVEVO", 221)], duration=None).matched is False
        assert pick([result("Interpol - Evil (Official Video)", "InterpolVEVO", 221)],
                    duration=None).matched


class TestRanking:
    def test_official_video_outranks_a_plain_upload_listed_first(self):
        plain = result("Interpol - Evil", "randomuploader", 221, video_id="plain")
        official = result("Interpol - Evil (Official Video)", "InterpolVEVO", 221, video_id="off")
        v = pick([plain, official])
        assert v.result is official

    def test_closest_duration_breaks_ties(self):
        near = result("Interpol - Evil", "InterpolVEVO", 222, video_id="near")
        far = result("Interpol - Evil", "InterpolVEVO", 250, video_id="far")
        v = pick([far, near])
        assert v.result is near

    def test_a_result_with_no_channel_is_refused_not_a_crash(self):
        """yt-dlp emits `"channel": null` for an upload whose channel is gone."""
        v = pick([result("Interpol - Evil", None, 221)])
        assert not v.matched

    def test_no_results_is_its_own_reason(self):
        assert pick([]).reason == "no results"


class TestTokens:
    def test_primary_artist_stops_at_the_guest(self):
        assert primary_artist("Gorillaz feat. De La Soul") == "Gorillaz"
        assert primary_artist("Simon & Garfunkel") == "Simon & Garfunkel"
        assert primary_artist("Belle and Sebastian") == "Belle and Sebastian"

    def test_leading_the_is_dropped_but_not_alone(self):
        assert artist_tokens("The National") == ["national"]
        assert artist_tokens("The The") == ["the"]

    def test_title_noise(self):
        assert title_tokens("Just Like Heaven (2006 Remaster)") == ["just", "like", "heaven"]
        assert title_tokens("Evil - 2011 Remaster") == ["evil"]
        assert title_tokens("He's on the Phone") == ["he", "on", "the", "phone"]
        assert title_tokens("(Live)") == ["live"]
