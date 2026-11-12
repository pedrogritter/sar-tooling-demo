# SAR glossary

The report reading may use this file as its only extra wording. The lines below are the belt's own limit sentences and the terms already used for these tools. A jargon word stays with the plain hint on the same line.

## Terms

- Sigma-nought is the brightness a calibrated tool reports, in decibels. Open water reports a median sigma-nought. Sea state reports the median sigma-nought of the water on each date. A lower bar is a darker sea, not a Beaufort number. Scan and Scan Wide GRDs are not radiometrically calibrated, so those tools do not report sigma-nought.
- Incidence is the scene incidence angle in degrees. Change and stack tools compare scenes with an incidence within 1 degree. X-band VV sea sigma-nought can fall by about a decibel per degree of incidence between 26° and 34°.
- Look side is left or right. Change and stack tools need the same look side and the same orbit direction.
- Overview scale is metres per overview pixel. When that size is not known, it is not available.
- Speckle is grain in the picture. Speckle and a residual shift can still fall in an amplitude-change area. The stack mean cuts speckle where the surface was stable. A surface that changed is blurred, not removed.
- Layover is part of a long bright return. The length is the bright return, layover included. An empty class is a valid result.
- Double-bounce is the bright return built-up reports. Brightness is a double-bounce return. It is not a building height and it is not a residential or industrial class.
- A bright return stays a bright radar return. The label stays bright return. A hull, a pier, and a platform all qualify.

## Belt limits

- Open water. Shadow, tarmac, and sand are dark for the same reason. Flooded vegetation and flooded streets get brighter, so this mask marks them dry.
- Sea roughness. This split is roughness, not a wave period, a wave height, or a current.
- Built-up return. Brightness is a double-bounce return. It is not a building height and it is not a residential or industrial class.
- Returns on water. A row is a bright radar return. A hull, a pier, and a platform all qualify.
- Long structure. The length is the bright return, layover included. An empty class is a valid result.
- Dwell motion. The stare is the length of this collect. A track is motion during those seconds, not a route.
- Amplitude change. The picture is a shared stretch. Red is the earlier date and cyan is the later date. Gray is where those two dates match. A difference under 3 dB, and a patch under 8 pixels, still take colour. The darker, brighter, and unchanged areas keep only a difference of at least 3 dB in a patch of at least 8 pixels. Speckle and a residual shift can still fall in those areas.
- Water persistence. Light blue is rare water. Solid blue is water on every date. Two dates are a pair, not a seasonal record.
- Sea state. The bars are the median sigma-nought of the water mask on each date. A lower bar is a darker sea, not a Beaufort number.
- Dark sea anomaly. A film is one cause. The same shape can be a biogenic film, a wind shadow, rain, or a current boundary. The title is dark sea anomaly.
- Shoreline. Each colour is one date. The shift is a waterline, not a tide height.
- Date of change. A pixel is coloured only when it leaves the stack median by 3 dB and the patch is at least 8 pixels.
- Repeat returns. Many dates is a rock, a pier, or a moored hull. One date is a passing return.
- Site activity. Cyan is a bright cluster new on this date. Red is a bright cluster the stack median had and this date does not.
- Stack mean. The mean uses at least five matched dates. Averaging cuts speckle where the surface was stable. A surface that changed is blurred, not removed.

## Dates

Stack tools compare every matched date, not only the chosen partner. Two dates are a pair, not a seasonal record.
