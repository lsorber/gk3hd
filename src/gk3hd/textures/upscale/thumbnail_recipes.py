"""Reviewed registration measurements and source mappings for inventory artwork."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ThumbnailRecipe:
    """One registered whole-image transform, never per-letter reshaping."""

    size: tuple[int, int]
    source_scale: float
    offset: tuple[float, float]
    source_name: str = "SNOTE6_ALPHA.BMP"
    source_size: tuple[int, int] = (601, 399)
    frame_inset: int = 0
    brightness: float = 1.0
    rotation_degrees: float = 0.0
    # Verified black-background object renders can contain actual holes. Solid
    # printed artwork instead needs enclosed black ink kept opaque.
    preserve_cutouts: bool = False
    # Some authored hover/pressed states change contrast as well as brightness.
    # This additive RGB offset applies to covered artwork, never its backdrop.
    brightness_offset: float = 0.0
    # Original clothing buttons sometimes use a different authored aspect ratio.
    # None preserves the normal uniform scale; this is not a free-form warp.
    source_scale_y: float | None = None
    source_color_key: tuple[int, int, int] | None = None
    # Two independently visible originals must agree on the shared backdrop,
    # including every visible row in the target; never extrapolate hidden rows.
    background_sources: tuple[str, str] | None = None


# Batch-verified matching scans; I_MON has different artwork/state geometry.
_FINGERPRINT_ACTION_SOURCES = (
    (
        "I_ABBEPRINT",
        "ABBEPRNT6_ALPHA.BMP",
        (305, 400),
        0.07390106005364502,
        (4.2549076049606045, 0.8781716266502851),
    ),
    (
        "I_BUCHPRNT",
        "BUCHPRNT6_ALPHA.BMP",
        (283, 392),
        0.07689403769424515,
        (5.281719746178424, 0.5635350053666609),
    ),
    (
        "I_VITPRNTWILNAME",
        "VITPRNTWILKESNAME6_ALPHA.BMP",
        (282, 386),
        0.07610982876575294,
        (5.36758338923927, 3.115179051154497),
    ),
    (
        "I_MADPRNT",
        "MADPRNT6_ALPHA.BMP",
        (284, 392),
        0.07576750867209633,
        (4.6589526870048, 1.803553000341649),
    ),
    (
        "I_ESTPRNTGAB",
        "ESTPRNT6_ALPHA.BMP",
        (291, 400),
        0.07511575722491916,
        (4.579026549699762, 2.538017361164176),
    ),
    (
        "I_ESTPRNTGRA",
        "ESTPRINTGRA6_ALPHA.BMP",
        (304, 400),
        0.07534068718225591,
        (5.018478581848951, 1.5178623912923415),
    ),
    (
        "I_LSRPRINTGRACE",
        "LSRPRINTESTELLE_6_ALPHA.BMP",
        (288, 400),
        0.07557569291417207,
        (5.393293367506155, 1.171651176489695),
    ),
    (
        "I_LHOPRNT",
        "LHOPRNT6_ALPHA.BMP",
        (320, 400),
        0.07736465269450123,
        (2.4800108735997384, 1.0268577562641106),
    ),
    (
        "I_LARPRNT",
        "LARPRNT6_ALPHA.BMP",
        (317, 400),
        0.07789462466091678,
        (3.394009498100841, 1.850761509464472),
    ),
    (
        "I_WILKESPRNT",
        "WILKESPRNT6_ALPHA.BMP",
        (304, 400),
        0.07563793441224233,
        (3.9215226746155447, 1.5035778026169073),
    ),
    (
        "I_WILNVIT",
        "WILKWBUCHPRNT6_ALPHA.BMP",
        (304, 399),
        0.07496695380752721,
        (3.3823456860886543, 1.4814690902593664),
    ),
)


# Matching printed pages share opaque ink, a three-pixel frame and the same
# normal/hover/pressed contract. Passports and mismatched card states are not
# members merely because their inventory metadata points to a larger image.
_DOCUMENT_ACTION_SOURCES = (
    (
        "I_VITLICENSE",
        "BUCLICPLATE6_ALPHA.BMP",
        (276, 387),
        0.0782526520169335,
        (5.7795574597847965, 2.4309903521355958),
    ),
    (
        "I_VITTRAINTICKET",
        "TICKET_6_ALPHA.BMP",
        (323, 238),
        0.0999152026008896,
        (0.4021787172636448, 5.87256141417053),
    ),
    (
        "I_NOTELERMITAGE",
        "L'ERMITAGE6_ALPHA.BMP",
        (352, 400),
        0.07381645052196292,
        (2.9013605574283816, 0.9589854855148328),
    ),
    (
        "I_NOTECARDOU",
        "CARDOU6_ALPHA.BMP",
        (348, 400),
        0.06765025378775935,
        (3.122040906777908, 2.0525711464639733),
    ),
    (
        "I_NOTEARMSE",
        "SNOTE6_ALPHA.BMP",
        (601, 399),
        0.060763530638216434,
        (-0.6690682320211895, 4.50772205476183),
    ),
    (
        "I_EMLLICENSE",
        "EMLLICPLATE6_ALPHA.BMP",
        (313, 392),
        0.07869203506895678,
        (3.156137964710122, 2.18809213196449),
    ),
    (
        "I_BBANKGRA",
        "GRA_BBANK6_ALPHA.BMP",
        (381, 263),
        0.08113725947541621,
        (-0.9072852794984095, 5.85919057466206),
    ),
    (
        "I_SHINEONGRA",
        "GRA_SHINEON6_ALPHA.BMP",
        (414, 279),
        0.07409234917522906,
        (-0.3496174559102295, 6.000103367996702),
    ),
    (
        "I_DIAPERGRA",
        "GRA_DIAPER6_ALPHA.BMP",
        (398, 299),
        0.07775412571524849,
        (-0.5552561076169759, 5.067842469365),
    ),
    (
        "I_NYTGRA",
        "GRA_NYT6_ALPHA.BMP",
        (405, 266),
        0.07755563057959287,
        (-1.2968122661017396, 6.316264397290252),
    ),
    (
        "I_FREELANCEGRA",
        "GRA_FREELANCE6_ALPHA.BMP",
        (427, 273),
        0.07248792482109159,
        (-0.2272019697252538, 6.803293042579137),
    ),
    (
        "I_LHOESTLICENSE",
        "LAHOESTLIC6_ALPHA.BMP",
        (312, 400),
        0.0764291959808126,
        (4.012039756924917, 3.362255211631596),
    ),
    (
        "I_LSR",
        "SERPENT6_ALPHA.BMP",
        (342, 399),
        0.06933248206398607,
        (3.261796139670518, 2.751288796864997),
    ),
)


# Whole-object matches, including dark details missed by paper-only analysis.
# Complete state families were checked; mismatched clothing remains separate.
_OBJECT_ACTION_SOURCES = (
    (
        "I_BLKMARKER",
        "BLACKMARKER_6_ALPHA.BMP",
        (422, 297),
        0.07034084443289267,
        (0.8979746508245621, 4.582992854029911),
    ),
    (
        "I_BUCHTAPE",
        "BUCHTAPE6_ALPHA.BMP",
        (411, 293),
        0.07515696192086335,
        (1.241122213201994, 5.570435637897814),
    ),
    (
        "I_GPS",
        "GPS_6_ALPHA.BMP",
        (393, 402),
        0.07844230926170587,
        (1.858275050562357, 1.9105060788400354),
    ),
    (
        "I_HANGER",
        "HANGER_6_ALPHA.BMP",
        (588, 230),
        0.054688745963986964,
        (0.5543242144947541, 10.924359018571124),
    ),
    (
        "I_LEATHERGLOVE",
        "LEATHERGLOVE6_ALPHA.BMP",
        (471, 391),
        0.06546134395244158,
        (0.1956890095432042, 2.7554409741144017),
    ),
    (
        "I_MEDALLION",
        "MEDALLION6_ALPHA.BMP",
        (243, 344),
        0.08571900552416571,
        (5.075263912365477, 0.5983363671461994),
    ),
    (
        "I_WILHANKY",
        "WILHANKY_6_ALPHA.BMP",
        (469, 358),
        0.06431650447206676,
        (1.330261555217696, 4.6484082653917245),
    ),
)


_RECIPES = {
    **{
        f"{family}_{state}.BMP": ThumbnailRecipe(
            (32, 32),
            factor,
            (
                offset[0] + (press_shift if state == "DWN" else 0),
                offset[1] + (press_shift if state == "DWN" else 0),
            ),
            source,
            dimensions,
            frame_inset=3,
            brightness=gain,
            rotation_degrees=rotation,
            brightness_offset=bias,
            source_color_key=color_key,
        )
        # Matching whole-page/photo originals, with independently measured
        # native tone and press conventions. The Temptation postcard keeps the
        # same interior in every state; Egypt changes tone without displacement.
        for family, source, dimensions, factor, offset, rotation, color_key, press_shift, tones in (
            (
                "I_MANILACLOSE",
                "MANILLAC6_ALPHA.BMP",
                (395, 368),
                0.06723693167506124,
                (2.1919832686441207, 4.357823917004378),
                -0.2214803436433777,
                None,
                1,
                (
                    (1.0036557289688455, 0.0),
                    (1.328791585657575, 0.859463409797844),
                    (0.8269093709256455, -0.5265430376667618),
                ),
            ),
            (
                "I_POEM",
                "POEMWONOTE6_ALPHA.BMP",
                (318, 400),
                0.07224721216566297,
                (2.4358103054376183, 2.8688878041366763),
                -8.85354570985931,
                None,
                1,
                (
                    (1.0049048716881914, 0.0),
                    (1.3240386448938006, 1.857934183414804),
                    (0.8293738915917303, -0.897918654990407),
                ),
            ),
            (
                "I_BLUEAPPLES",
                "BLUEAPPLE6_ALPHA.BMP",
                (640, 400),
                0.07191997700249321,
                (-8.233610342484802, 2.0260630856919857),
                -0.6528025754057061,
                None,
                1,
                (
                    (1.0138739042008045, 0.0),
                    (1.2519082101365109, 7.692346393890428),
                    (0.8020403929002163, -1.648115575431208),
                ),
            ),
            (
                "I_EGYPTP",
                "EGYPTPHOTO6_ALPHA.BMP",
                (441, 375),
                0.056619019991857915,
                (3.0843368239935582, 4.991757069121141),
                -0.009429091324549135,
                None,
                0,
                (
                    (0.9772266578525545, 0.0),
                    (1.2358068952380648, 13.984752464234),
                    (0.7896003186892119, -7.275704178455968),
                ),
            ),
            (
                "I_GRACEPASS",
                "GRA_PASSOPEN6_ALPHA.BMP",
                (274, 335),
                0.07591739539256312,
                (5.077075278223852, 3.213006064746933),
                -0.3893919298786763,
                None,
                1,
                (
                    (1.009482485490558, 0.0),
                    (1.4015199544579282, 10.476999695928898),
                    (0.8198041853638639, -11.632974448287952),
                ),
            ),
            (
                "I_NOTEARMNE",
                "NENOTE6_ALPHA.BMP",
                (640, 400),
                0.07349388088765345,
                (-7.428624753639845, 0.7400623385311036),
                -0.014532760291931233,
                (255, 0, 255),
                1,
                (
                    (1.0048596918312553, 0.0),
                    (1.3267365477012698, 1.3793840482723674),
                    (0.8247274237613766, -0.17844087549134793),
                ),
            ),
            (
                "I_PCARDSTANSTP",
                "STASTP6_ALPHA.BMP",
                (485, 338),
                0.054487256239808365,
                (1.8108337175328089, 7.7505404733597665),
                0.2591480808652149,
                None,
                1,
                (
                    (1.077012025539233, 0.0),
                    (1.4173736272003754, 1.438093314296634),
                    (0.8841277678868171, -0.20803662190994654),
                ),
            ),
            (
                "I_PCARDTEMPTATION",
                "TEMPSTANT6_ALPHA.BMP",
                (291, 370),
                0.07370104488108344,
                (5.0242706064811635, 0.444797449885419),
                0.3911309656257341,
                None,
                0,
                ((1.4106232402629553, 0.0), (1.4106232402629553, 0.0), (1.4106232402629553, 0.0)),
            ),
            (
                "I_WILLETTER",
                "WILKESLETR6_ALPHA.BMP",
                (325, 383),
                0.0761577080094326,
                (2.9489620002209413, 4.9328914552675975),
                -5.302739472739923,
                None,
                1,
                (
                    (1.014368914289938, 0.0),
                    (1.3352952856040246, 1.6938564847026107),
                    (0.8377762325719303, -1.0263111874198054),
                ),
            ),
            (
                "I_WILLICENSE",
                "WILLICPLATE6_ALPHA.BMP",
                (356, 400),
                0.08150080918332474,
                (2.4456884420339104, 3.970875261626709),
                0.42987200331479275,
                None,
                1,
                (
                    (1.0091734466579885, 0.0),
                    (1.3288565760500783, 1.5576094564449234),
                    (0.825961791309621, 0.06941104453708317),
                ),
            ),
        )
        for state, (gain, bias) in zip(("STD", "HOV", "DWN"), tones, strict=True)
    },
    **{
        f"{family}_{state}.BMP": ThumbnailRecipe(
            (32, 32),
            factor_x,
            offset,
            source,
            dimensions,
            frame_inset=3,
            brightness=gain,
            brightness_offset=bias,
            source_scale_y=factor_y,
            source_color_key=color_key,
        )
        # Independent fits of all three native states confirm these original
        # whole-image proportions and stationary pressed artwork.
        for family, source, dimensions, factor_x, factor_y, offset, color_key, tones in (
            (
                "I_BLKMOUSTACHE",
                "BLKMUSTACHE_6_ALPHA.BMP",
                (582, 229),
                0.04388504962660655,
                0.06988853570492232,
                (2.8680466591032077, 7.783758180999096),
                None,
                (
                    (1.4124183074451353, 0.0),
                    (1.8415025677457801, 21.36172701148742),
                    (1.173728095619231, -13.00715571038871),
                ),
            ),
            (
                "I_CAPNSTASH",
                "CAPNSTASH_6_ALPHA.BMP",
                (573, 371),
                0.05046318276149471,
                0.0655646855666222,
                (1.6341325035524956, 4.868872262781215),
                None,
                (
                    (1.0132283918297516, 0.0),
                    (1.3523278739310292, 8.647385825449048),
                    (0.8554606052458376, -18.983925511318425),
                ),
            ),
            (
                "I_COATNSTASH",
                "COATNSTASH_6_ALPHA.BMP",
                (339, 388),
                0.05754801436510948,
                0.07114925595609435,
                (5.469146961344081, 1.1353137098454247),
                None,
                (
                    (1.0119912298021148, 0.0),
                    (1.243169567161145, 6.408101395828398),
                    (0.8725845102783967, -14.065976239089613),
                ),
            ),
            (
                "I_GLDBLAZER",
                "BLAZER_6_ALPHA.BMP",
                (640, 480),
                0.05709944320397142,
                0.0705150683930834,
                (-3.2613455794219193, -1.4978045277128886),
                (255, 0, 255),
                (
                    (1.0131427631509458, 0.0),
                    (1.1721901956335556, 11.484839405006696),
                    (0.8425734111816646, -12.75246856647021),
                ),
            ),
        )
        for state, (gain, bias) in zip(("STD", "HOV", "DWN"), tones, strict=True)
    },
    **{
        f"{family}_{state}.BMP": ThumbnailRecipe(
            (32, 32),
            factor,
            (
                offset[0] + (pressed_shift if state == "DWN" else 0),
                offset[1] + (pressed_shift if state == "DWN" else 0),
            ),
            source,
            dimensions,
            frame_inset=3,
            brightness=base_gain * gain,
            brightness_offset=bias,
        )
        # These original clothing states have measured affine tone changes.
        # The coat/cap artwork stays in place when pressed; the cap moves 1px.
        for family, source, dimensions, factor, offset, base_gain, pressed_shift, tones in (
            (
                "I_HAT",
                "HAT_6_ALPHA.BMP",
                (533, 347),
                0.050988227717381415,
                (1.4746595425748703, 6.579248738460966),
                0.9881552484418503,
                1,
                (
                    (1.0, 0.0),
                    (1.4625360940901972, 18.482580564650696),
                    (0.8400668659807591, -21.526093987568473),
                ),
            ),
            (
                "I_COATNCAP",
                "COATNCAP_6_ALPHA.BMP",
                (412, 366),
                0.06672072055156525,
                (0.5581852816554895, 3.3877440013146485),
                1.008628469743187,
                0,
                (
                    (1.0, 0.0),
                    (1.267994537226071, 4.237689090360602),
                    (0.8228591850681549, -4.949242803629888),
                ),
            ),
        )
        for state, (gain, bias) in zip(("STD", "HOV", "DWN"), tones, strict=True)
    },
    **{
        f"{family}_{state}.BMP": ThumbnailRecipe(
            (32, 32),
            factor,
            (offset[0] + shift, offset[1] + shift),
            source,
            dimensions,
            frame_inset=3,
            brightness=brightness,
            preserve_cutouts=family in {"I_MOSROOMKEY", "I_MOPEDKEY", "I_HANGER", "I_MEDALLION"},
        )
        # Shipped object/document buttons and their matching inventory artwork.
        # One whole-image transform preserves lettering and perspective.
        for family, source, dimensions, factor, offset in (
            *_FINGERPRINT_ACTION_SOURCES,
            *_DOCUMENT_ACTION_SOURCES,
            *_OBJECT_ACTION_SOURCES,
            (
                "I_CANDY",
                "CANDY6_ALPHA.BMP",
                (263, 158),
                0.12236528202902223,
                (0.6868882187717642, 6.930938363111748),
            ),
            (
                "I_TIRETRACK",
                "TIRETRACE6_ALPHA.BMP",
                (280, 361),
                0.08580752588528641,
                (4.028209214388661, 0.8509713830719823),
            ),
            (
                "I_SYRUP",
                "SYRUP6_ALPHA.BMP",
                (243, 154),
                0.13264016761125272,
                (0.2955137444297392, 5.5910141649303435),
            ),
            (
                "I_BINOCS",
                "BINOCS_6_ALPHA.BMP",
                (260, 373),
                0.0756655279408172,
                (5.9048440690984885, 1.8449083594830729),
            ),
            (
                "I_SHOVEL",
                "SHOVEL6_ALPHA.BMP",
                (640, 400),
                0.05334862402242576,
                (-4.06973413296858, 5.157915103955631),
            ),
            (
                "I_HOLYGRAILBOOK",
                "HBHGBK6_ALPHA.BMP",
                (425, 406),
                0.07222222222188265,
                (0.40993668886334655, 1.332313097560018),
            ),
            (
                "I_NOTEBOOKGRA",
                "GRANOTEBK6_ALPHA.BMP",
                (290, 310),
                0.09849334501881964,
                (1.0670872721047555, 1.3539951807786514),
            ),
            (
                "I_MOPEDKEY",
                "SCOOTERKEY6_ALPHA.BMP",
                (342, 230),
                0.10869546656878777,
                (-6.923755668615829, 3.024129100439295),
            ),
            (
                "I_CHURCHPAMPHLET",
                "CHUPAM6_ALPHA.BMP",
                (624, 416),
                0.06136879548147263,
                (-3.4039401014047175, 2.5076195516501465),
            ),
            (
                "I_GLASS",
                "GLASS_6_ALPHA.BMP",
                (272, 373),
                0.08268858992986662,
                (3.8672867921022305, 1.9854575617134218),
            ),
            (
                "I_PCARDPOUTOMB",
                "POUTOMB6_ALPHA.BMP",
                (433, 312),
                0.06516658589793485,
                (2.1482287321270905, 6.139195524771306),
            ),
            (
                "I_TAPERECORDER",
                "MINIRCRDER6_ALPHA.BMP",
                (405, 296),
                0.07836879428316444,
                (0.05484779078148037, 5.4994849846379585),
            ),
            (
                "I_DAGGER",
                "DAGGER6_ALPHA.BMP",
                (640, 378),
                0.04585294606342739,
                (1.505903083971077, 8.755592652792423),
            ),
            (
                "I_GRAWALLET",
                "GRACEWALLET6_ALPHA.BMP",
                (400, 218),
                0.075,
                (2.5776758227883496, 10.106262367808883),
            ),
            (
                "I_PJAMES",
                "PJAMESBIZCARD6_ALPHA.BMP",
                (346, 195),
                0.0963509952649265,
                (-0.8485688965883986, 6.867848610977664),
            ),
            (
                "I_MOSROOMKEY",
                "ROOMKEY6_ALPHA.BMP",
                (369, 202),
                0.08844743123942134,
                (0.2754203049545, 8.269012087926178),
            ),
            (
                "I_MAP",
                "MAP6_ALPHA.BMP",
                (433, 383),
                0.06687468275662163,
                (1.3222368249784509, 4.595383655753991),
            ),
            (
                "I_MANU",
                "MANU6_ALPHA.BMP",
                (347, 400),
                0.07440322060405978,
                (2.583251437391417, 1.67130356235189),
            ),
            (
                "I_PARCH1",
                "PARCH1_6_ALPHA.BMP",
                (335, 397),
                0.07710473750129329,
                (3.7219748512779574, 3.4165994732637848),
            ),
            (
                "I_PARCH2",
                "PARCH2_6_ALPHA.BMP",
                (334, 398),
                0.07689319379023833,
                (3.504434699724171, 1.825656695750855),
            ),
            (
                "I_NOTEBOOKGAB",
                "NOTEBK6_ALPHA.BMP",
                (249, 329),
                0.08276108304506259,
                (5.582577365069248, 2.5581384003095664),
            ),
            (
                "I_BBANKGAB",
                "BBANK6_ALPHA.BMP",
                (483, 339),
                0.0638541904072085,
                (1.252779402904827, 5.1309100275875865),
            ),
            (
                "I_SHINEONGAB",
                "SHINEON6_ALPHA.BMP",
                (433, 312),
                0.07066332950269696,
                (1.4132086837926923, 5.000272738472104),
            ),
            (
                "I_DIAPERGAB",
                "DIAPER6_ALPHA.BMP",
                (513, 340),
                0.05783602044910616,
                (0.8176255871567573, 6.2415989208678795),
            ),
            (
                "I_NYTGAB",
                "NYT6_ALPHA.BMP",
                (436, 302),
                0.07215531766883486,
                (-0.2792308804871187, 5.988588551928494),
            ),
        )
        for state, brightness, shift in (("STD", 1.0, 0), ("HOV", 4 / 3, 0), ("DWN", 5 / 6, 1))
    },
    **{
        f"I_ABBETAPE_{state}.BMP": ThumbnailRecipe(
            (32, 32),
            0.06484752797567819,
            (3.03786000020771 + shift, 5.82798216301456 + shift),
            "ABBETAPE6_ALPHA.BMP",
            (400, 310),
            frame_inset=3,
            brightness=brightness,
        )
        for state, brightness, shift in (("STD", 1.0, 0), ("HOV", 4 / 3, 0), ("DWN", 5 / 6, 1))
    },
    **{
        f"I_PASSPORTMOS_{state}.BMP": ThumbnailRecipe(
            (32, 32),
            0.07610632974580675,
            (-0.46529790497047085 + shift, 14.834240045515594 + shift),
            "PASSOPEN6_ALPHA.BMP",
            (260, 331),
            frame_inset=3,
            brightness=brightness,
            rotation_degrees=-45,
        )
        for state, brightness, shift in (("STD", 1.0, 0), ("HOV", 4 / 3, 0), ("DWN", 5 / 6, 1))
    },
    "UNDEFINED9.BMP": ThumbnailRecipe(
        (94, 94),
        0.2358972065689303,
        (-28.61895288069762, -0.8512964338982961),
        "UNDEFINED6.BMP",
        (640, 400),
    ),
    **{
        f"I_PASSPORTMOSDIS_{state}.BMP": ThumbnailRecipe(
            (32, 32),
            0.08280410640350634,
            (5.156143758219466 + shift, 2.2466968292323903 + shift),
            "PASSOPENDIS6_ALPHA.BMP",
            (254, 335),
            frame_inset=3,
            brightness=brightness,
        )
        for state, brightness, shift in (("STD", 1.0, 0), ("HOV", 4 / 3, 0), ("DWN", 5 / 6, 1))
    },
    "SNOTE3.BMP": ThumbnailRecipe(
        (32, 30), 0.06132462935684347, (-0.8209329503245738, 2.388883267806804)
    ),
    "SNOTE9.BMP": ThumbnailRecipe(
        (94, 94), 0.14978116591253288, (2.837351449514391, 16.76910783569999)
    ),
    "GRANOTEBK3.BMP": ThumbnailRecipe(
        (30, 32),
        0.09904700048993637,
        (-0.023634292061004866, 0.24658464424671214),
        "GRANOTEBK6_ALPHA.BMP",
        (290, 310),
    ),
    "GRANOTEBK9.BMP": ThumbnailRecipe(
        (94, 94),
        0.2576184888221059,
        (9.276932137616708, 8.242385312466485),
        "GRANOTEBK6_ALPHA.BMP",
        (290, 310),
    ),
    # The riddle's close-up has different line breaks and perspective. Only
    # BLUEAPPLE, not BLUEAPPLE6_ALPHA, matches the original small views.
    "BLUEAPPLE3.BMP": ThumbnailRecipe(
        (32, 31),
        0.06453551188470354,
        (-5.654521806144458, -0.46190955692066044),
        "BLUEAPPLE.BMP",
        (640, 480),
    ),
    "BLUEAPPLE9.BMP": ThumbnailRecipe(
        (94, 94),
        0.19965934480428624,
        (-22.080726542270437, -0.32318124256028596),
        "BLUEAPPLE.BMP",
        (640, 480),
    ),
}
# Whole-card registrations verified against each legacy state's original pixels.
# Shared inventory nouns are not source evidence; these explicit names preserve
# the distinct manuscript scans and their authored hover/pressed relationships.
_SCAN_ACTION_RECIPES = {
    name: ThumbnailRecipe(
        (32, 32),
        scale,
        (offset[0] + shift, offset[1] + shift),
        source,
        source_size,
        frame_inset=3,
        brightness=gain,
        brightness_offset=tone_offset,
        rotation_degrees=rotation,
    )
    for names, source, source_size, scale, offset, rotation, gains, tone_offsets in (
        (
            ("SNOTE.BMP", "SNOTE_HOV.BMP", "SNOTED.BMP"),
            "SNOTE6_ALPHA.BMP",
            (601, 399),
            0.060747071032253436,
            (0.38332843224641877, 5.450513836385538),
            0.22566690110692553,
            (1.008457112886281, 1.3322703509611118, 0.8283207490085045),
            (0, 1.2174344562488484, -0.20702987344164267),
        ),
        (
            ("I_LSRPRINTGABE.BMP", "I_LSRPRINTGABE_HOV.BMP", "I_LSRPRINTGABED.BMP"),
            "LSRPRINTGRACE_6_ALPHA.BMP",
            (293, 400),
            0.07563667251245594,
            (4.2365723325839095, 0.5825112817077507),
            -0.16893360439092164,
            (1.0069872689164545, 1.3263738585636236, 0.827844276909469),
            (0, 0.9181625682488085, -0.23023581658176365),
        ),
        (
            ("I_MANU1PRINT.BMP", "I_MANU1PRINT_HOV.BMP", "I_MANU1PRINTD.BMP"),
            "MANU1PRINT_6_ALPHA.BMP",
            (283, 400),
            0.07474299429370346,
            (5.212176779188843, 1.4729161439379688),
            0.02433131853899969,
            (1.0079108358380886, 1.3338787154799099, 0.8308279687422421),
            (0, 0.6786342488241682, -0.6214936081982235),
        ),
        (
            ("I_MANU2PRINT.BMP", "I_MANU2PRINT_HOV.BMP", "I_MANU2PRINTD.BMP"),
            "MANU2PRINT_6_ALPHA.BMP",
            (288, 400),
            0.07561947601342175,
            (5.001347638496366, 2.291444863747266),
            -0.24386975643987394,
            (1.0116643305639745, 1.3372161659037056, 0.8334379044092705),
            (0, 0.7072732457977625, -0.5203100485871888),
        ),
        (
            ("I_MANU3PRINT.BMP", "I_MANU3PRINT_HOV.BMP", "I_MANU3PRINTD.BMP"),
            "MANU3PRINT_6_ALPHA.BMP",
            (304, 400),
            0.07716252791908507,
            (4.125260986482598, 1.0792177775986485),
            -0.03847689255828187,
            (1.010750275105643, 1.340955333422088, 0.8342017512831525),
            (0, 0.6486455372186143, -1.0512163753802182),
        ),
        (
            ("I_MOSPRNT_STD.BMP", "I_MOSPRNT_HOV.BMP", "I_MOSPRNT_DWN.BMP"),
            "MOSELYPRINT_6_ALPHA.BMP",
            (307, 400),
            0.07525740686807354,
            (3.5930533424486732, 1.375923517920075),
            0.08861615528271265,
            (1.0100031119119963, 1.3328426167833003, 0.8355244548273377),
            (0, 1.177458269845182, -1.2325248080556368),
        ),
    )
    for name, gain, tone_offset, shift in zip(names, gains, tone_offsets, (0, 0, 1), strict=True)
}
_RECIPES.update(_SCAN_ACTION_RECIPES)
# These legacy blood-bank action states have exactly the same decoded pixels
# as the corresponding reviewed states, including their frame and pressed shift.
# Share the immutable recipe; do not infer aliases from similar names or nouns.
_RECIPES.update(
    {
        f"I_GABBBANK_{state}.BMP": _RECIPES[f"I_BBANKGAB_{state}.BMP"]
        for state in ("STD", "HOV", "DWN")
    }
)
# Only this alternate spelling/state exists in the shipped BMP catalog. Its
# pixels equal the reviewed hover original; infer no other states from the name.
_RECIPES["I_ABBEPRNT_HOV.BMP"] = _RECIPES["I_ABBEPRINT_HOV.BMP"]
# Reviewed rendered items retain the original whole-object geometry and state
# artwork. Only the wallet's larger source uses a magenta color key. The old
# complete-disguise button has no pressed translation, unlike these other items.
_RECIPES.update(
    {
        name: ThumbnailRecipe(
            (32, 32),
            scale,
            (offset[0] + shift, offset[1] + shift),
            source,
            source_size,
            frame_inset=3,
            brightness=gain,
            brightness_offset=tone_offset,
            rotation_degrees=rotation,
            source_color_key=color_key,
            preserve_cutouts=cutouts,
        )
        for (
            names,
            source,
            source_size,
            scale,
            offset,
            rotation,
            gains,
            tone_offsets,
            color_key,
            shifts,
            cutouts,
        ) in (
            (
                ("I_FREELANCEGAB_STD.BMP", "I_FREELANCEGAB_HOV.BMP", "I_FREELANCEGAB_DWN.BMP"),
                "FREELANCE6_ALPHA.BMP",
                (483, 331),
                0.06298934543053601,
                (1.3097172627815301, 5.635416540476189),
                0.018749858151247946,
                (1.00717927144953, 1.3318214972927371, 0.8316345243483507),
                (0, 0.933236596067033, -0.6919915763622487),
                None,
                (0, 0, 1),
                False,
            ),
            (
                ("I_GABWALLET_STD.BMP", "I_GABWALLET_HOV.BMP", "I_GABWALLET_DWN.BMP"),
                "GABEWALLET6_ALPHA.BMP",
                (640, 400),
                0.08728762787608621,
                (-12.399014631497963, 0.159923177555745),
                -0.22751497142377197,
                (0.9087511314657055, 1.1995989827047504, 0.7486000191760862),
                (0, 1.078873887106301, -0.6174852072422722),
                (255, 0, 255),
                (0, 0, 1),
                False,
            ),
            (
                ("I_PREPH_STD.BMP", "I_PREPH_HOV.BMP", "I_PREPH_DWN.BMP"),
                "PREPH6_ALPHA.BMP",
                (361, 348),
                0.07340893815423224,
                (0.8147441552255658, 5.964577413095784),
                -0.01849544069616264,
                (0.9790970129438603, 1.2946400653592673, 0.8115326981506462),
                (0, 1.0803740006637055, -0.8908791336148115),
                None,
                (0, 0, 1),
                False,
            ),
            (
                ("I_FINGRPRNTKIT.BMP", "I_FINGRPRNTKIT_HOV.BMP", "I_FINGRPRNTKITD.BMP"),
                "FINGRPRNTKIT6_ALPHA.BMP",
                (629, 298),
                0.0514151999893914,
                (-0.35921313002579847, 9.249048251320431),
                0.023351971356714653,
                (1.143211341568802, 1.5151148878899345, 0.9425825342985753),
                (0, 1.0479006241554947, -0.6786828456841975),
                None,
                (0, 0, 1),
                False,
            ),
            (
                ("I_COATNSTASHNCAP.BMP", "I_COATNSTASHNCAP_HOV.BMP", "I_COATNSTASHNCAPD.BMP"),
                "COATNSTASHNCAP_6_ALPHA.BMP",
                (429, 382),
                0.0639168991314657,
                (2.56352831701795, 3.4285001523538416),
                -0.22941110538686083,
                (1.0097403508366585, 1.283955704468179, 0.8527252797598512),
                (0, 6.715305154275632, -11.50542862269316),
                None,
                (0, 0, 0),
                False,
            ),
            (
                ("I_PHOTOEGYPT_STD.BMP", "I_PHOTOEGYPT_HOV.BMP", "I_PHOTOEGYPT_DWN.BMP"),
                "EGYPTPHOTO6_ALPHA.BMP",
                (441, 375),
                0.05947795135835751,
                (2.178225227847873, 4.993615191613343),
                -0.03610020081201537,
                (0.9644616946435212, 1.2793337559750617, 0.7970426865995763),
                (0, 0.5714462322132977, -0.7834681615126855),
                None,
                (0, 0, 1),
                False,
            ),
            (
                ("I_HARLEYKEY_STD.BMP", "I_HARLEYKEY_HOV.BMP", "I_HARLEYKEY_DWN.BMP"),
                "HDKEY6_ALPHA.BMP",
                (306, 187),
                0.13197601593968022,
                (2.967016971943334, 4.375423594222182),
                -0.1747596398685118,
                (1.031123430218531, 1.3631148801685697, 0.8539952272864018),
                (0, 1.0751046141326681, -1.5012732750820197),
                None,
                (0, 0, 1),
                True,
            ),
            (
                ("I_MANILAOPEN_STD.BMP", "I_MANILAOPEN_HOV.BMP", "I_MANILAOPEN_DWN.BMP"),
                "MANILLAO6_ALPHA.BMP",
                (395, 376),
                0.06911245030918427,
                (0.9146783926394393, 3.9842498045694255),
                -0.3094194715568009,
                (1.0100476841299548, 1.3352034060135265, 0.8331494542891706),
                (0, 0.896612063976216, -0.875249486205857),
                None,
                (0, 0, 1),
                False,
            ),
            (
                ("I_FAKEID.BMP", "I_FAKEID_HOV.BMP", "I_FAKEIDD.BMP"),
                "FAKEID6_ALPHA.BMP",
                (285, 375),
                0.07629267552606571,
                (4.74125668772556, 2.6763308182550736),
                -0.01514981109996843,
                (1.0103329232918907, 1.3299988630063146, 0.829686071082557),
                (0, 1.5663145834347156, -0.0919182365987134),
                None,
                (0, 0, 1),
                False,
            ),
        )
        for name, gain, tone_offset, shift in zip(names, gains, tone_offsets, shifts, strict=True)
    }
)
_RECIPES.update(
    {
        f"I_MOSLICENSE_{state}.BMP": ThumbnailRecipe(
            (32, 32),
            0.07843640057006723,
            (0.009685698187118064 + shift, 2.9735883583363467 + shift),
            "MOSLICPLATE6_ALPHA.BMP",
            (369, 398),
            frame_inset=3,
            brightness=gain,
            brightness_offset=bias,
            rotation_degrees=0.1984448631688079,
            background_sources=("I_BLKMARKER_DWN.BMP", "I_DAGGER_DWN.BMP") if shift else None,
        )
        for state, shift, gain, bias in (
            ("STD", 0, 1.0080638717002222, 0.0),
            ("HOV", 0, 1.3350461966614238, 0.8858309243741816),
            ("DWN", 1, 0.8248462166677655, 0.20496742598909437),
        )
    }
)
FRAMED_THUMBNAIL_SIZES = {
    name: recipe.size for name, recipe in _RECIPES.items() if recipe.frame_inset
}
# These originals use the engine's RGB565 format, including the opaque fallback.
RGB565_THUMBNAIL_SIZES = FRAMED_THUMBNAIL_SIZES | {"UNDEFINED9.BMP": (94, 94)}


def thumbnail_recipe(name: str) -> ThumbnailRecipe | None:
    """Select only correspondences verified against the original small views."""
    return _RECIPES.get(Path(name).name.upper())
