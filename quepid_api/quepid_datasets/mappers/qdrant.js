// Response mapper for a Qdrant points/search response, for a Quepid search
// endpoint with search_engine="searchapi" -- Quepid cannot read Qdrant by
// itself. Pass it as `create_case --mapper-code-file`.
//
// Verbatim from part 2 of "How to evaluate image search in Qdrant using Quepid",
// which is also where `thumb` comes from: Quepid renders it as the result's
// thumbnail, which is the whole point of judging an image search.
// https://frutik.medium.com/how-to-evaluate-image-search-in-qdrant-using-quepid-and-the-hacks-it-takes-part-2-hacks-39ed553cd97a
numberOfResultsMapper = function(data){
  return data.result.length;
};

docsMapper = function(data){
  let docs = [];
  for (let doc of data.result) {
    docs.push ({
      id: doc.id,
      thumb: doc.payload.image,
      title: doc.payload.title,
    });
  }
  return docs;
};
